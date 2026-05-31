"""
GitHub Integration -- webhook verification, REST API client,
and PR/commit status operations.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
GITHUB_API_BASE = "https://api.github.com"


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not GITHUB_WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


class GitHubClient:
    """
    Async GitHub REST API client.
    Falls back to logging operations when no token is configured.
    """

    def __init__(self, token: str = "") -> None:
        self._token = token or GITHUB_TOKEN
        self._http = None

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"token {self._token}"
        return h

    async def _get_client(self):
        if self._http is None:
            import httpx
            self._http = httpx.AsyncClient(headers=self._headers(), timeout=30.0)
        return self._http

    async def create_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        description: str,
        context: str = "intellipipeline",
        target_url: str = "",
    ) -> dict[str, Any]:
        if not self._token:
            logger.info("github.commit_status_simulated", state=state, sha=sha, description=description)
            return {"state": state, "description": description, "simulated": True}
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/statuses/{sha}",
                json={"state": state, "description": description[:140],
                      "context": context, "target_url": target_url},
            )
            return resp.json()
        except Exception as e:
            logger.warning("github.commit_status_failed", error=str(e))
            return {"error": str(e)}

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self._token:
            logger.info("github.pr_simulated", title=title, head=head, base=base)
            return {"number": 0, "html_url": "#", "simulated": True, "title": title}
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
                json={"title": title, "body": body, "head": head, "base": base},
            )
            pr = resp.json()
            if labels and pr.get("number"):
                await client.post(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr['number']}/labels",
                    json={"labels": labels},
                )
            return pr
        except Exception as e:
            logger.warning("github.pr_creation_failed", error=str(e))
            return {"error": str(e)}

    async def add_pr_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> dict[str, Any]:
        if not self._token:
            logger.info("github.comment_simulated", pr=pr_number)
            return {"simulated": True}
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments",
                json={"body": body},
            )
            return resp.json()
        except Exception as e:
            logger.warning("github.comment_failed", error=str(e))
            return {"error": str(e)}

    async def get_pr_files(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        if not self._token:
            return []
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
            )
            return resp.json() if resp.status_code == 200 else []
        except Exception as e:
            logger.warning("github.get_files_failed", error=str(e))
            return []

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

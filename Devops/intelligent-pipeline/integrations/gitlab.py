"""
GitLab Integration -- webhook handling and REST API client.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "")
GITLAB_API_BASE = os.environ.get("GITLAB_URL", "https://gitlab.com") + "/api/v4"


def verify_webhook_token(request_token: str) -> bool:
    if not GITLAB_TOKEN:
        return True
    return request_token == GITLAB_TOKEN


class GitLabClient:
    """Async GitLab REST API client with simulation fallback."""

    def __init__(self, token: str = "") -> None:
        self._token = token or GITLAB_TOKEN
        self._http = None

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["PRIVATE-TOKEN"] = self._token
        return h

    async def _get_client(self):
        if self._http is None:
            import httpx
            self._http = httpx.AsyncClient(headers=self._headers(), timeout=30.0)
        return self._http

    async def set_commit_status(
        self,
        project_id: str,
        sha: str,
        state: str,
        name: str = "intellipipeline",
        description: str = "",
        target_url: str = "",
    ) -> dict[str, Any]:
        if not self._token:
            logger.info("gitlab.commit_status_simulated", state=state, sha=sha)
            return {"state": state, "simulated": True}
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{GITLAB_API_BASE}/projects/{project_id}/statuses/{sha}",
                json={"state": state, "name": name,
                      "description": description[:250], "target_url": target_url},
            )
            return resp.json()
        except Exception as e:
            logger.warning("gitlab.commit_status_failed", error=str(e))
            return {"error": str(e)}

    async def create_merge_request(
        self,
        project_id: str,
        title: str,
        description: str,
        source_branch: str,
        target_branch: str = "main",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self._token:
            logger.info("gitlab.mr_simulated", title=title)
            return {"iid": 0, "web_url": "#", "simulated": True}
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{GITLAB_API_BASE}/projects/{project_id}/merge_requests",
                json={
                    "title": title, "description": description,
                    "source_branch": source_branch, "target_branch": target_branch,
                    "labels": ",".join(labels or []),
                },
            )
            return resp.json()
        except Exception as e:
            logger.warning("gitlab.mr_creation_failed", error=str(e))
            return {"error": str(e)}

    async def add_mr_note(
        self, project_id: str, mr_iid: int, body: str
    ) -> dict[str, Any]:
        if not self._token:
            logger.info("gitlab.note_simulated", mr=mr_iid)
            return {"simulated": True}
        try:
            client = await self._get_client()
            resp = await client.post(
                f"{GITLAB_API_BASE}/projects/{project_id}/merge_requests/{mr_iid}/notes",
                json={"body": body},
            )
            return resp.json()
        except Exception as e:
            logger.warning("gitlab.note_failed", error=str(e))
            return {"error": str(e)}

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

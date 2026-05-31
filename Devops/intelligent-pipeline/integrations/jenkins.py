"""
Jenkins Integration -- job triggering and build status polling.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

JENKINS_URL = os.environ.get("JENKINS_URL", "http://jenkins:8080")
JENKINS_USER = os.environ.get("JENKINS_USER", "admin")
JENKINS_TOKEN = os.environ.get("JENKINS_TOKEN", "")


class JenkinsClient:
    """Async Jenkins REST API client with simulation fallback."""

    def __init__(self, url: str = "", user: str = "", token: str = "") -> None:
        self._url = (url or JENKINS_URL).rstrip("/")
        self._user = user or JENKINS_USER
        self._token = token or JENKINS_TOKEN
        self._http = None

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._user and self._token:
            cred = base64.b64encode(f"{self._user}:{self._token}".encode()).decode()
            h["Authorization"] = f"Basic {cred}"
        return h

    async def _get_client(self):
        if self._http is None:
            import httpx
            self._http = httpx.AsyncClient(headers=self._headers(), timeout=30.0)
        return self._http

    async def trigger_build(
        self, job_name: str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._token:
            logger.info("jenkins.build_simulated", job=job_name)
            return {"queued": True, "job": job_name, "simulated": True}
        try:
            client = await self._get_client()
            if parameters:
                resp = await client.post(
                    f"{self._url}/job/{job_name}/buildWithParameters",
                    params=parameters,
                )
            else:
                resp = await client.post(f"{self._url}/job/{job_name}/build")
            return {"queued": resp.status_code in (200, 201), "status_code": resp.status_code}
        except Exception as e:
            logger.warning("jenkins.trigger_failed", error=str(e))
            return {"error": str(e)}

    async def get_build_status(
        self, job_name: str, build_number: int = -1
    ) -> dict[str, Any]:
        if not self._token:
            return {"result": "UNKNOWN", "simulated": True}
        try:
            client = await self._get_client()
            build = "lastBuild" if build_number == -1 else str(build_number)
            resp = await client.get(
                f"{self._url}/job/{job_name}/{build}/api/json"
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "result": data.get("result", "IN_PROGRESS"),
                    "building": data.get("building", False),
                    "duration_ms": data.get("duration", 0),
                    "url": data.get("url", ""),
                    "number": data.get("number", build_number),
                }
            return {"result": "UNKNOWN", "status_code": resp.status_code}
        except Exception as e:
            logger.warning("jenkins.status_failed", error=str(e))
            return {"error": str(e)}

    async def get_build_log(
        self, job_name: str, build_number: int = -1
    ) -> str:
        if not self._token:
            return ""
        try:
            client = await self._get_client()
            build = "lastBuild" if build_number == -1 else str(build_number)
            resp = await client.get(
                f"{self._url}/job/{job_name}/{build}/consoleText"
            )
            return resp.text if resp.status_code == 200 else ""
        except Exception as e:
            logger.warning("jenkins.log_failed", error=str(e))
            return ""

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

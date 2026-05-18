"""
Copilot / natural language query routes.
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = structlog.get_logger(__name__)
router = APIRouter()

COPILOT_URL = os.environ.get("COPILOT_SERVICE_URL", "http://copilot-service:8007")


class CopilotQuery(BaseModel):
    query: str
    context: dict = {}
    stream: bool = False


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.post("/query")
async def natural_language_query(
    body: CopilotQuery,
    request: Request,
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """
    Execute a natural language query against enterprise data.

    Examples:
    - "Find duplicate suppliers"
    - "Which datasets have low trust scores?"
    - "Show customer hierarchy for Acme Corp"
    - "Which systems violate data governance policies?"
    """
    if body.stream:
        async def event_stream() -> AsyncGenerator[str, None]:
            async with client.stream(
                "POST",
                f"{COPILOT_URL}/copilot/query/stream",
                json=body.model_dump(),
            ) as resp:
                async for chunk in resp.aiter_text():
                    yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    resp = await client.post(f"{COPILOT_URL}/copilot/query", json=body.model_dump())
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/suggestions")
async def get_query_suggestions(
    context: str = "",
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """Get suggested queries based on current data context."""
    resp = await client.get(f"{COPILOT_URL}/copilot/suggestions", params={"context": context})
    return resp.json()

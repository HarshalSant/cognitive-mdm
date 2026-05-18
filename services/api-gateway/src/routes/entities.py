"""
Entity CRUD and search routes — proxies to entity-resolution service.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

logger = structlog.get_logger(__name__)
router = APIRouter()

ENTITY_RESOLUTION_URL = os.environ.get("ENTITY_RESOLUTION_URL", "http://entity-resolution:8002")


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def proxy_get(client: httpx.AsyncClient, path: str, params: dict = None) -> Any:
    resp = await client.get(f"{ENTITY_RESOLUTION_URL}{path}", params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


async def proxy_post(client: httpx.AsyncClient, path: str, body: dict) -> Any:
    resp = await client.post(f"{ENTITY_RESOLUTION_URL}{path}", json=body)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/")
async def list_entities(
    entity_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """List entities with optional filters."""
    params = {"limit": limit, "offset": offset}
    if entity_type:
        params["entity_type"] = entity_type
    if status:
        params["status"] = status
    return await proxy_get(client, "/entities/", params)


@router.get("/{entity_id}")
async def get_entity(entity_id: str, client: httpx.AsyncClient = Depends(get_http_client)):
    """Get a single entity by ID."""
    return await proxy_get(client, f"/entities/{entity_id}")


@router.post("/")
async def create_entity(body: dict, client: httpx.AsyncClient = Depends(get_http_client)):
    """Create a new entity."""
    return await proxy_post(client, "/entities/", body)


@router.post("/search")
async def search_entities(body: dict, client: httpx.AsyncClient = Depends(get_http_client)):
    """Semantic + keyword entity search."""
    return await proxy_post(client, "/entities/search", body)


@router.post("/{entity_id}/resolve")
async def resolve_entity(
    entity_id: str,
    body: dict,
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """Trigger entity resolution for a specific entity."""
    return await proxy_post(client, f"/entities/{entity_id}/resolve", body)


@router.get("/{entity_id}/duplicates")
async def find_duplicates(
    entity_id: str,
    threshold: float = Query(default=0.8),
    limit: int = Query(default=10),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """Find duplicate candidates for an entity."""
    params = {"threshold": threshold, "limit": limit}
    return await proxy_get(client, f"/entities/{entity_id}/duplicates", params)


@router.get("/{entity_id}/lineage")
async def get_entity_lineage(
    entity_id: str,
    depth: int = Query(default=3),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    """Get data lineage for an entity."""
    params = {"depth": depth}
    return await proxy_get(client, f"/entities/{entity_id}/lineage", params)

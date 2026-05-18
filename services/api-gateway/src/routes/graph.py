"""Graph exploration and lineage routes."""

from __future__ import annotations

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter()
GRAPH_URL = os.environ.get("GRAPH_SERVICE_URL", "http://graph-service:8004")


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/neighborhood/{node_id}")
async def get_neighborhood(
    node_id: str,
    depth: int = Query(default=2, le=5),
    rel_types: str = Query(default=""),
    client: httpx.AsyncClient = Depends(get_client),
):
    """Get graph neighborhood around a node."""
    params = {"depth": depth}
    if rel_types:
        params["rel_types"] = rel_types
    resp = await client.get(f"{GRAPH_URL}/graph/neighborhood/{node_id}", params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/path")
async def find_path(
    source_id: str = Query(...),
    target_id: str = Query(...),
    max_hops: int = Query(default=5),
    client: httpx.AsyncClient = Depends(get_client),
):
    """Find shortest path between two entities."""
    params = {"source_id": source_id, "target_id": target_id, "max_hops": max_hops}
    resp = await client.get(f"{GRAPH_URL}/graph/path", params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/impact/{node_id}")
async def impact_analysis(
    node_id: str,
    client: httpx.AsyncClient = Depends(get_client),
):
    """Analyze downstream impact if this entity were changed or removed."""
    resp = await client.get(f"{GRAPH_URL}/graph/impact/{node_id}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.post("/query")
async def cypher_query(
    body: dict,
    client: httpx.AsyncClient = Depends(get_client),
):
    """Execute a read-only Cypher query (admin only)."""
    resp = await client.post(f"{GRAPH_URL}/graph/query", json=body)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()

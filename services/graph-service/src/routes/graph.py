"""Graph query and exploration routes."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = structlog.get_logger(__name__)
router = APIRouter()


def get_neo4j(request: Request):
    return request.app.state.neo4j


@router.get("/neighborhood/{node_id}")
async def get_neighborhood(
    node_id: str,
    depth: int = Query(default=2, le=5),
    rel_types: str = Query(default=""),
    request: Request = None,
):
    client = get_neo4j(request)
    types = [t.strip() for t in rel_types.split(",") if t.strip()] if rel_types else None
    return await client.get_neighborhood(node_id, depth, types)


@router.get("/path")
async def find_path(
    source_id: str = Query(...),
    target_id: str = Query(...),
    max_hops: int = Query(default=5, le=10),
    request: Request = None,
):
    client = get_neo4j(request)
    return await client.find_path(source_id, target_id, max_hops)


@router.get("/impact/{node_id}")
async def impact_analysis(node_id: str, request: Request = None):
    client = get_neo4j(request)
    return await client.impact_analysis(node_id)


@router.post("/query")
async def cypher_query(body: dict, request: Request = None):
    """Execute a read-only Cypher query."""
    query = body.get("query", "")
    params = body.get("params", {})
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    # Restrict to read-only operations
    lowered = query.strip().upper()
    if not lowered.startswith("MATCH") and not lowered.startswith("RETURN"):
        raise HTTPException(status_code=403, detail="Only read queries (MATCH/RETURN) are allowed")
    client = get_neo4j(request)
    records = await client.run(query, params)
    return {"results": records, "count": len(records)}


@router.post("/entity")
async def upsert_entity(body: dict, request: Request = None):
    """Upsert an entity node into the graph."""
    client = get_neo4j(request)
    await client.upsert_entity_node(body)
    return {"status": "upserted", "id": body.get("id")}


@router.post("/relationship")
async def create_relationship(body: dict, request: Request = None):
    """Create a typed relationship between two entity nodes."""
    client = get_neo4j(request)
    await client.create_relationship(
        source_id=body["source_id"],
        target_id=body["target_id"],
        rel_type=body["rel_type"],
        props=body.get("props", {}),
    )
    return {"status": "created"}

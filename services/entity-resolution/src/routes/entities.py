"""
Entity CRUD routes for the entity-resolution service.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


def get_engine(request: Request):
    return request.app.state.resolution_engine


@router.get("/")
async def list_entities(
    entity_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
):
    conditions = ["deleted_at IS NULL"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if entity_type:
        conditions.append("entity_type = :entity_type")
        params["entity_type"] = entity_type
    if status:
        conditions.append("status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    result = await db.execute(
        text(f"SELECT id, entity_type, status, fields, tags, created_at FROM entities WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    )
    rows = result.mappings().all()
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM entities WHERE {where}"),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    total = count_result.scalar()
    return {"entities": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{entity_id}")
async def get_entity(entity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM entities WHERE id = :id AND deleted_at IS NULL"),
        {"id": entity_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return dict(row)


@router.post("/")
async def create_entity(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    entity_id = str(uuid.uuid4())
    entity_type = body.get("entity_type", "customer")
    fields = body.get("fields", {})
    tags = body.get("tags", [])
    metadata = body.get("metadata", {})

    await db.execute(
        text("""
            INSERT INTO entities (id, entity_type, status, fields, tags, metadata)
            VALUES (:id, :entity_type, 'pending', :fields, :tags, :metadata)
        """),
        {
            "id": entity_id,
            "entity_type": entity_type,
            "fields": __import__("json").dumps(fields),
            "tags": tags,
            "metadata": __import__("json").dumps(metadata),
        },
    )

    engine = get_engine(request)
    await engine.index_entity(entity_id, entity_type, fields)

    return {"id": entity_id, "entity_type": entity_type, "status": "pending"}


@router.post("/search")
async def search_entities(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    query_text = body.get("query", "")
    entity_type = body.get("entity_type")
    limit = min(body.get("limit", 20), 100)
    semantic = body.get("semantic", True)

    results = []
    if semantic and query_text:
        engine = get_engine(request)
        semantic_matches = await engine.semantic.find_similar(
            entity_type=entity_type or "customer",
            fields={"name": query_text},
            limit=limit,
            threshold=0.50,
        )
        entity_ids = [m.entity_id for m in semantic_matches]
        if entity_ids:
            placeholders = ", ".join(f":id_{i}" for i in range(len(entity_ids)))
            id_params = {f"id_{i}": eid for i, eid in enumerate(entity_ids)}
            result = await db.execute(
                text(f"SELECT id, entity_type, status, fields, tags FROM entities WHERE id IN ({placeholders})"),
                id_params,
            )
            rows = result.mappings().all()
            # Preserve semantic ranking order
            id_order = {eid: i for i, eid in enumerate(entity_ids)}
            results = sorted([dict(r) for r in rows], key=lambda r: id_order.get(r["id"], 999))

    return {"entities": results, "total": len(results), "semantic_used": semantic}


@router.get("/{entity_id}/duplicates")
async def find_duplicates(
    entity_id: str,
    threshold: float = Query(default=0.8),
    limit: int = Query(default=10),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT fields, entity_type FROM entities WHERE id = :id"),
        {"id": entity_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")

    engine = get_engine(request)
    matches = await engine.semantic.find_similar(
        entity_type=row["entity_type"],
        fields=row["fields"] if isinstance(row["fields"], dict) else __import__("json").loads(row["fields"]),
        limit=limit,
        threshold=threshold,
        exclude_ids=[entity_id],
    )
    return {
        "entity_id": entity_id,
        "candidates": [
            {"entity_id": m.entity_id, "score": m.score, "method": "semantic"}
            for m in matches
        ],
    }


@router.get("/{entity_id}/lineage")
async def get_lineage(
    entity_id: str,
    depth: int = Query(default=3),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT * FROM entity_sources WHERE entity_id = :id"),
        {"id": entity_id},
    )
    sources = [dict(r) for r in result.mappings().all()]
    return {"entity_id": entity_id, "sources": sources, "depth": depth}

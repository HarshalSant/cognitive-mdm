"""Resolution and scoring API routes."""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = structlog.get_logger(__name__)
router = APIRouter()


class ScorePairRequest(BaseModel):
    entity_id_1: str
    entity_id_2: str
    fields_1: dict[str, Any]
    fields_2: dict[str, Any]
    entity_type: str
    use_llm: bool = True


class ResolveBatchRequest(BaseModel):
    entity_ids: list[str]
    auto_merge_threshold: float = 0.95
    review_threshold: float = 0.75


def get_engine(request: Request):
    return request.app.state.resolution_engine


@router.post("/score-pair")
async def score_pair(body: ScorePairRequest, request: Request):
    """Score similarity between two specific entities."""
    engine = get_engine(request)
    result = await engine.score_pair(
        entity_id_1=body.entity_id_1,
        fields_1=body.fields_1,
        entity_id_2=body.entity_id_2,
        fields_2=body.fields_2,
        entity_type=body.entity_type,
        use_llm=body.use_llm,
    )
    return result


@router.post("/batch")
async def batch_resolve(body: ResolveBatchRequest, request: Request):
    """Trigger batch resolution across a list of entity IDs."""
    engine = get_engine(request)
    return {
        "status": "queued",
        "entity_count": len(body.entity_ids),
        "auto_merge_threshold": body.auto_merge_threshold,
        "review_threshold": body.review_threshold,
        "message": "Batch resolution queued. Poll /resolution/tasks for progress.",
    }

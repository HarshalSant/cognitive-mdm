"""Governance API routes: trust scoring, PII scanning, policy evaluation."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()


def get_trust_scorer(request: Request):
    return request.app.state.trust_scorer

def get_pii_detector(request: Request):
    return request.app.state.pii_detector

def get_policy_engine(request: Request):
    return request.app.state.policy_engine


@router.get("/trust/{entity_id}")
async def get_trust_score(
    entity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT * FROM trust_scores WHERE entity_id = :id ORDER BY computed_at DESC LIMIT 1"),
        {"id": entity_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Trust score not found -- run /scan first")
    return dict(row)


@router.post("/trust/batch")
async def batch_trust_scores(body: dict, request: Request, db: AsyncSession = Depends(get_db)):
    entity_ids: list[str] = body.get("entity_ids", [])
    if not entity_ids:
        raise HTTPException(status_code=400, detail="entity_ids required")

    placeholders = ", ".join(f":id_{i}" for i in range(len(entity_ids)))
    params = {f"id_{i}": eid for i, eid in enumerate(entity_ids)}
    result = await db.execute(
        text(f"""
            SELECT DISTINCT ON (entity_id) *
            FROM trust_scores
            WHERE entity_id IN ({placeholders})
            ORDER BY entity_id, computed_at DESC
        """),
        params,
    )
    scores = [dict(r) for r in result.mappings().all()]
    return {"scores": scores, "total": len(scores)}


@router.get("/violations")
async def list_violations(
    severity: str | None = Query(None),
    status: str | None = Query(None),
    entity_type: str | None = Query(None),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    conditions = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if severity:
        conditions.append("gv.severity = :severity")
        params["severity"] = severity
    if status:
        conditions.append("gv.status = :status")
        params["status"] = status

    where = " AND ".join(conditions)
    result = await db.execute(
        text(f"""
            SELECT gv.*, gp.name as policy_name, gp.policy_type
            FROM governance_violations gv
            LEFT JOIN governance_policies gp ON gv.policy_id = gp.id
            WHERE {where}
            ORDER BY gv.detected_at DESC
            LIMIT :limit
        """),
        params,
    )
    return {"violations": [dict(r) for r in result.mappings().all()]}


@router.post("/scan/{entity_id}")
async def scan_entity(
    entity_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Full governance scan: PII detection + policy evaluation + trust score computation."""
    result = await db.execute(
        text("SELECT * FROM entities WHERE id = :id"),
        {"id": entity_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity = dict(row)
    fields = entity.get("fields") or {}
    if isinstance(fields, str):
        import json
        fields = json.loads(fields)

    entity_type = entity.get("entity_type", "customer")

    # 1. PII detection
    pii_detector = get_pii_detector(request)
    pii_detections = pii_detector.scan_entity(entity_id, fields)

    # 2. Policy evaluation
    policy_engine = get_policy_engine(request)
    violations = policy_engine.evaluate(
        entity_id=entity_id,
        entity_type=entity_type,
        fields=fields,
        pii_detections=pii_detections,
    )

    # 3. Trust scoring
    trust_scorer = get_trust_scorer(request)
    import datetime
    updated_at = entity.get("updated_at")
    if isinstance(updated_at, str):
        updated_at = datetime.datetime.fromisoformat(updated_at)
    trust = trust_scorer.compute(
        entity_id=entity_id,
        entity_type=entity_type,
        fields=fields,
        sources=[],
        updated_at=updated_at,
    )

    # 4. Persist trust score
    await db.execute(
        text("""
            INSERT INTO trust_scores
                (entity_id, overall_score, completeness, consistency, recency, source_reliability, tier)
            VALUES
                (:entity_id, :overall, :completeness, :consistency, :recency, :source_reliability, :tier)
        """),
        {
            "entity_id": entity_id,
            "overall": trust.overall,
            "completeness": trust.completeness,
            "consistency": trust.consistency,
            "recency": trust.recency,
            "source_reliability": trust.source_reliability,
            "tier": trust.tier,
        },
    )

    return {
        "entity_id": entity_id,
        "trust_score": trust.to_dict(),
        "pii_detections": [
            {"field": d.field_path, "type": d.pii_type, "confidence": d.confidence}
            for d in pii_detections
        ],
        "violations": [
            {
                "policy": v.policy_name,
                "type": v.violation_type,
                "severity": v.severity,
                "description": v.description,
            }
            for v in violations
        ],
    }


@router.get("/policies")
async def list_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT * FROM governance_policies ORDER BY name"))
    return {"policies": [dict(r) for r in result.mappings().all()]}

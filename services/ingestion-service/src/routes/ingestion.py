"""Ingestion API routes: CSV upload, batch ingest, batch status."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..processors.csv_processor import process_csv

logger = structlog.get_logger(__name__)
router = APIRouter()

_batches: dict[str, dict[str, Any]] = {}


def get_kafka(request: Request):
    return request.app.state.kafka


@router.post("/upload/csv")
async def upload_csv(
    file: UploadFile = File(...),
    entity_type: str = Query(default="customer"),
    source_name: str = Query(default="csv_upload"),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    batch_id = str(uuid.uuid4())
    records = process_csv(content, entity_type, source_name)

    if not records:
        raise HTTPException(status_code=400, detail="No valid records found in CSV")

    _batches[batch_id] = {
        "batch_id": batch_id,
        "status": "processing",
        "total": len(records),
        "processed": 0,
        "failed": 0,
        "source": source_name,
        "entity_type": entity_type,
        "started_at": datetime.utcnow().isoformat(),
    }

    kafka = get_kafka(request)
    processed = 0
    failed = 0

    for record in records:
        try:
            await db.execute(
                text("""
                    INSERT INTO entities (id, entity_type, status, fields, metadata)
                    VALUES (:id, :entity_type, 'pending', :fields, :metadata)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": record["id"],
                    "entity_type": record["entity_type"],
                    "fields": __import__("json").dumps(record["fields"]),
                    "metadata": __import__("json").dumps({"source": source_name, "batch_id": batch_id}),
                },
            )
            await kafka.send(
                "mdm.entity.ingested",
                {
                    "entity_id": record["id"],
                    "entity_type": entity_type,
                    "fields": record["fields"],
                    "source_name": source_name,
                    "batch_id": batch_id,
                },
                key=record["id"],
            )
            processed += 1
        except Exception as e:
            logger.error("ingestion.record_failed", error=str(e))
            failed += 1

    _batches[batch_id].update({
        "status": "completed",
        "processed": processed,
        "failed": failed,
        "completed_at": datetime.utcnow().isoformat(),
    })

    return {
        "batch_id": batch_id,
        "total": len(records),
        "processed": processed,
        "failed": failed,
        "entity_type": entity_type,
        "source": source_name,
    }


@router.post("/batch")
async def ingest_batch(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    records = body.get("records", [])
    entity_type = body.get("entity_type", "customer")
    source_name = body.get("source_name", "api_integration")

    if not records:
        raise HTTPException(status_code=400, detail="No records provided")

    batch_id = str(uuid.uuid4())
    kafka = get_kafka(request)
    processed = 0

    for rec in records[:1000]:  # Safety cap
        entity_id = rec.get("id") or str(uuid.uuid4())
        fields = rec.get("fields") or {k: v for k, v in rec.items() if k != "id"}
        try:
            await db.execute(
                text("""
                    INSERT INTO entities (id, entity_type, status, fields, metadata)
                    VALUES (:id, :entity_type, 'pending', :fields, :metadata)
                    ON CONFLICT (id) DO UPDATE SET fields = EXCLUDED.fields, updated_at = NOW()
                """),
                {
                    "id": entity_id,
                    "entity_type": entity_type,
                    "fields": __import__("json").dumps(fields),
                    "metadata": __import__("json").dumps({"source": source_name, "batch_id": batch_id}),
                },
            )
            await kafka.send(
                "mdm.entity.ingested",
                {"entity_id": entity_id, "entity_type": entity_type, "fields": fields, "source_name": source_name},
                key=entity_id,
            )
            processed += 1
        except Exception as e:
            logger.error("batch.record_failed", error=str(e))

    return {"batch_id": batch_id, "processed": processed, "total": len(records)}


@router.get("/batches")
async def list_batches():
    return {"batches": list(_batches.values()), "total": len(_batches)}


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str):
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch

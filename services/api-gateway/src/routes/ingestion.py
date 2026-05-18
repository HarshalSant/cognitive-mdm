"""Data ingestion routes."""

from __future__ import annotations

import os
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

router = APIRouter()
INGESTION_URL = os.environ.get("INGESTION_SERVICE_URL", "http://ingestion-service:8001")


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.post("/upload/csv")
async def upload_csv(
    file: UploadFile = File(...),
    entity_type: str = "customer",
    source_name: str = "csv_upload",
    client: httpx.AsyncClient = Depends(get_client),
):
    content = await file.read()
    resp = await client.post(
        f"{INGESTION_URL}/ingestion/upload/csv",
        files={"file": (file.filename, content, "text/csv")},
        params={"entity_type": entity_type, "source_name": source_name},
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.post("/batch")
async def ingest_batch(body: dict, client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.post(f"{INGESTION_URL}/ingestion/batch", json=body)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/batches")
async def list_batches(client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.get(f"{INGESTION_URL}/ingestion/batches")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/batches/{batch_id}")
async def get_batch_status(batch_id: str, client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.get(f"{INGESTION_URL}/ingestion/batches/{batch_id}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()

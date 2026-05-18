"""Governance, trust scoring, and PII detection routes."""

from __future__ import annotations

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

router = APIRouter()
GOVERNANCE_URL = os.environ.get("GOVERNANCE_SERVICE_URL", "http://governance-service:8005")


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/trust/{entity_id}")
async def get_trust_score(entity_id: str, client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.get(f"{GOVERNANCE_URL}/governance/trust/{entity_id}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.post("/trust/batch")
async def batch_trust_scores(body: dict, client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.post(f"{GOVERNANCE_URL}/governance/trust/batch", json=body)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/violations")
async def list_violations(
    severity: str | None = Query(None),
    status: str | None = Query(None),
    entity_type: str | None = Query(None),
    limit: int = Query(default=50, le=200),
    client: httpx.AsyncClient = Depends(get_client),
):
    params = {"limit": limit}
    if severity:
        params["severity"] = severity
    if status:
        params["status"] = status
    if entity_type:
        params["entity_type"] = entity_type
    resp = await client.get(f"{GOVERNANCE_URL}/governance/violations", params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.post("/scan/{entity_id}")
async def scan_entity(entity_id: str, client: httpx.AsyncClient = Depends(get_client)):
    """Full governance scan: PII detection + policy evaluation + trust scoring."""
    resp = await client.post(f"{GOVERNANCE_URL}/governance/scan/{entity_id}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/policies")
async def list_policies(client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.get(f"{GOVERNANCE_URL}/governance/policies")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()

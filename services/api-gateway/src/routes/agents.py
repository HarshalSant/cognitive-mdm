"""Agent orchestration routes."""

from __future__ import annotations

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter()
AGENT_URL = os.environ.get("AGENT_SERVICE_URL", "http://agent-service:8006")


def get_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.post("/run")
async def run_agent(body: dict, client: httpx.AsyncClient = Depends(get_client)):
    """Trigger an autonomous AI agent task."""
    resp = await client.post(f"{AGENT_URL}/agents/run", json=body)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/tasks")
async def list_tasks(client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.get(f"{AGENT_URL}/agents/tasks")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.get(f"{AGENT_URL}/agents/tasks/{task_id}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


@router.post("/tasks/{task_id}/approve")
async def approve_remediation(task_id: str, client: httpx.AsyncClient = Depends(get_client)):
    resp = await client.post(f"{AGENT_URL}/agents/tasks/{task_id}/approve")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()

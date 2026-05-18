"""Agent task management routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = structlog.get_logger(__name__)
router = APIRouter()

# In-memory task store (use Redis/DB in production)
_tasks: dict[str, dict[str, Any]] = {}


class RunAgentRequest(BaseModel):
    agent_type: str
    task_description: str = ""
    entity_ids: list[str] = []
    parameters: dict[str, Any] = {}


def get_registry(request: Request):
    return request.app.state.registry


@router.post("/run")
async def run_agent(body: RunAgentRequest, request: Request):
    """Trigger an autonomous agent task."""
    registry = get_registry(request)
    try:
        agent = registry.get(body.agent_type)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown agent type: {body.agent_type}")

    task_id = str(uuid.uuid4())
    task_input = {
        "entity_ids": body.entity_ids,
        **body.parameters,
    }

    _tasks[task_id] = {
        "task_id": task_id,
        "agent_type": body.agent_type,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "input": task_input,
    }

    try:
        result = await agent.run(task_input)
        _tasks[task_id].update({
            "status": "completed",
            "result": result,
            "completed_at": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        logger.error("agent.task_failed", task_id=task_id, error=str(e))
        _tasks[task_id].update({
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.utcnow().isoformat(),
        })

    return _tasks[task_id]


@router.get("/tasks")
async def list_tasks():
    return {"tasks": list(_tasks.values()), "total": len(_tasks)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str):
    """Approve a pending remediation task."""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _tasks[task_id]["human_approved"] = True
    _tasks[task_id]["approved_at"] = datetime.utcnow().isoformat()
    return {"status": "approved", "task_id": task_id}


@router.get("/types")
async def list_agent_types(request: Request):
    registry = get_registry(request)
    return {"agent_types": list(registry.agents.keys())}

"""
CognitiveMDM Agent Service
LangGraph-powered autonomous AI agents for data stewardship.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents.registry import AgentRegistry
from .routes import agents, health

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("agent_service.starting")
    registry = AgentRegistry()
    await registry.initialize()
    app.state.registry = registry
    logger.info("agent_service.ready", agents=list(registry.agents.keys()))
    yield
    logger.info("agent_service.stopped")


app = FastAPI(title="Agent Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router, prefix="/health")
app.include_router(agents.router, prefix="/agents")

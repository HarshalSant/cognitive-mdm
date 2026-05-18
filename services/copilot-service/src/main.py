"""
CognitiveMDM Copilot Service
Natural language interface to enterprise data using GraphRAG + Claude.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .nlp.query_engine import CopilotQueryEngine
from .routes import copilot, health

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("copilot_service.starting")
    engine = CopilotQueryEngine()
    await engine.initialize()
    app.state.query_engine = engine
    logger.info("copilot_service.ready")
    yield
    await engine.close()
    logger.info("copilot_service.stopped")


app = FastAPI(title="Copilot Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router, prefix="/health")
app.include_router(copilot.router, prefix="/copilot")

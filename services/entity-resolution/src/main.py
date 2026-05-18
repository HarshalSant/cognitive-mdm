"""
CognitiveMDM Entity Resolution Service
AI-powered duplicate detection, probabilistic matching, and golden record creation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .resolvers.engine import ResolutionEngine
from .routes import entities, resolution, health
from .consumers.kafka_consumer import start_consumer

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("entity_resolution.starting")
    await init_db()

    engine = ResolutionEngine()
    await engine.initialize()
    app.state.resolution_engine = engine

    consumer_task = start_consumer(engine)

    logger.info("entity_resolution.ready")
    yield

    consumer_task.cancel()
    await engine.close()
    logger.info("entity_resolution.stopped")


app = FastAPI(
    title="Entity Resolution Service",
    description="AI-powered entity deduplication and golden record management",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health")
app.include_router(entities.router, prefix="/entities")
app.include_router(resolution.router, prefix="/resolution")

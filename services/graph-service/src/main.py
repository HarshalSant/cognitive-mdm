"""
CognitiveMDM Graph Service
Neo4j-backed knowledge graph: entity nodes, relationships, lineage, impact analysis.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .graph.neo4j_client import Neo4jClient
from .routes import graph, lineage, health

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("graph_service.starting")
    client = Neo4jClient()
    await client.initialize()
    app.state.neo4j = client
    logger.info("graph_service.ready")
    yield
    await client.close()
    logger.info("graph_service.stopped")


app = FastAPI(title="Graph Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router, prefix="/health")
app.include_router(graph.router, prefix="/graph")
app.include_router(lineage.router, prefix="/lineage")

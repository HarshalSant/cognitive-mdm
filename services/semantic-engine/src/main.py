"""
CognitiveMDM Semantic Engine
Ontology generation, taxonomy inference, embedding management, semantic search.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .embeddings.manager import EmbeddingManager
from .ontology.generator import OntologyGenerator
from .routes import semantic, health

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("semantic_engine.starting")
    embedding_manager = EmbeddingManager()
    await embedding_manager.initialize()
    app.state.embeddings = embedding_manager
    app.state.ontology = OntologyGenerator()
    logger.info("semantic_engine.ready")
    yield
    logger.info("semantic_engine.stopped")


app = FastAPI(title="Semantic Engine", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router, prefix="/health")
app.include_router(semantic.router, prefix="/semantic")

"""
CognitiveMDM Governance Service
PII detection, policy evaluation, trust scoring, compliance enforcement.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .trust.scorer import TrustScorer
from .pii.detector import PIIDetector
from .policies.engine import PolicyEngine
from .routes import governance, health

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("governance_service.starting")
    await init_db()
    app.state.trust_scorer = TrustScorer()
    app.state.pii_detector = PIIDetector()
    app.state.policy_engine = await PolicyEngine.create()
    logger.info("governance_service.ready")
    yield
    logger.info("governance_service.stopped")


app = FastAPI(title="Governance Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router, prefix="/health")
app.include_router(governance.router, prefix="/governance")

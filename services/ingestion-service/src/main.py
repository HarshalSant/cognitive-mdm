"""
CognitiveMDM Ingestion Service
Multi-source data ingestion: CSV, REST API, streaming, batch.
Normalises records and emits EntityIngestedEvent to Kafka.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .producers.kafka_producer import KafkaProducer
from .routes import ingestion, health

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("ingestion_service.starting")
    await init_db()
    producer = KafkaProducer()
    await producer.start()
    app.state.kafka = producer
    logger.info("ingestion_service.ready")
    yield
    await producer.stop()
    logger.info("ingestion_service.stopped")


app = FastAPI(title="Ingestion Service", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router, prefix="/health")
app.include_router(ingestion.router, prefix="/ingestion")

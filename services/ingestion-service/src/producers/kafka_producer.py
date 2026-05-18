"""Kafka producer for the ingestion service."""

from __future__ import annotations

import json
import os

import structlog
from aiokafka import AIOKafkaProducer

logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")


class KafkaProducer:
    def __init__(self):
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v, default=str).encode(),
                compression_type="gzip",
            )
            await self._producer.start()
            logger.info("kafka_producer.started")
        except Exception as e:
            logger.warning("kafka_producer.start_failed", error=str(e))
            self._producer = None

    async def send(self, topic: str, value: dict, key: str | None = None) -> None:
        if not self._producer:
            logger.warning("kafka_producer.not_available", topic=topic)
            return
        key_bytes = key.encode() if key else None
        await self._producer.send(topic, value=value, key=key_bytes)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

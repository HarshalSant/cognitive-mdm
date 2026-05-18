"""
Kafka consumer for entity-resolution service.
Listens for EntityIngestedEvent and triggers resolution pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os

import structlog
from aiokafka import AIOKafkaConsumer

logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
CONSUMER_GROUP = os.environ.get("KAFKA_CONSUMER_GROUP", "entity-resolution")
TOPIC = "mdm.entity.ingested"


def start_consumer(engine) -> asyncio.Task:
    return asyncio.create_task(_consume(engine))


async def _consume(engine) -> None:
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=CONSUMER_GROUP,
        auto_offset_reset="earliest",
        value_deserializer=lambda v: json.loads(v.decode()),
    )
    try:
        await consumer.start()
        logger.info("kafka_consumer.started", topic=TOPIC)
        async for msg in consumer:
            try:
                event = msg.value
                entity_id = event.get("entity_id")
                entity_type = event.get("entity_type")
                fields = event.get("fields", {})
                if entity_id and entity_type:
                    await engine.index_entity(entity_id, entity_type, fields)
            except Exception as e:
                logger.error("kafka_consumer.processing_error", error=str(e))
    except asyncio.CancelledError:
        pass
    finally:
        await consumer.stop()
        logger.info("kafka_consumer.stopped")

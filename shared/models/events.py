"""
Kafka event schemas for CognitiveMDM.
All events are versioned and schema-validated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    # Ingestion
    ENTITY_INGESTED = "entity.ingested"
    ENTITY_UPDATED = "entity.updated"
    BATCH_INGESTED = "batch.ingested"

    # Resolution
    ENTITY_RESOLVED = "entity.resolved"
    DUPLICATE_DETECTED = "duplicate.detected"
    ENTITY_MERGED = "entity.merged"

    # Semantic
    EMBEDDING_CREATED = "embedding.created"
    ONTOLOGY_UPDATED = "ontology.updated"
    TAXONOMY_INFERRED = "taxonomy.inferred"

    # Graph
    LINEAGE_CREATED = "lineage.created"
    RELATIONSHIP_EXTRACTED = "relationship.extracted"
    GRAPH_UPDATED = "graph.updated"

    # Governance
    TRUST_SCORE_UPDATED = "trust_score.updated"
    PII_DETECTED = "pii.detected"
    GOVERNANCE_VIOLATION = "governance.violation"
    POLICY_APPLIED = "policy.applied"

    # Agent
    AGENT_TASK_STARTED = "agent.task.started"
    AGENT_TASK_COMPLETED = "agent.task.completed"
    REMEDIATION_APPLIED = "remediation.applied"


# Kafka topic mapping
TOPIC_MAP: dict[EventType, str] = {
    EventType.ENTITY_INGESTED: "mdm.entity.ingested",
    EventType.ENTITY_UPDATED: "mdm.entity.updated",
    EventType.BATCH_INGESTED: "mdm.batch.ingested",
    EventType.ENTITY_RESOLVED: "mdm.entity.resolved",
    EventType.DUPLICATE_DETECTED: "mdm.duplicate.detected",
    EventType.ENTITY_MERGED: "mdm.entity.merged",
    EventType.EMBEDDING_CREATED: "mdm.embedding.created",
    EventType.ONTOLOGY_UPDATED: "mdm.ontology.updated",
    EventType.LINEAGE_CREATED: "mdm.lineage.created",
    EventType.RELATIONSHIP_EXTRACTED: "mdm.relationship.extracted",
    EventType.TRUST_SCORE_UPDATED: "mdm.trust_score.updated",
    EventType.PII_DETECTED: "mdm.pii.detected",
    EventType.GOVERNANCE_VIOLATION: "mdm.governance.violation",
    EventType.AGENT_TASK_STARTED: "mdm.agent.task.started",
    EventType.AGENT_TASK_COMPLETED: "mdm.agent.task.completed",
    EventType.REMEDIATION_APPLIED: "mdm.remediation.applied",
}


class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    schema_version: str = "1.0"
    produced_at: datetime = Field(default_factory=datetime.utcnow)
    source_service: str
    correlation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def topic(self) -> str:
        return TOPIC_MAP.get(self.event_type, f"mdm.{self.event_type.value}")

    def partition_key(self) -> str:
        return self.correlation_id or self.event_id


class EntityIngestedEvent(BaseEvent):
    event_type: EventType = EventType.ENTITY_INGESTED
    entity_id: str
    entity_type: str
    source_name: str
    field_count: int
    has_pii: bool = False
    batch_id: str | None = None

    def partition_key(self) -> str:
        return self.entity_id


class EntityResolvedEvent(BaseEvent):
    event_type: EventType = EventType.ENTITY_RESOLVED
    entity_id: str
    golden_record_id: str
    confidence: float
    method: str
    merged_count: int = 0

    def partition_key(self) -> str:
        return self.golden_record_id


class DuplicateDetectedEvent(BaseEvent):
    event_type: EventType = EventType.DUPLICATE_DETECTED
    entity_id_1: str
    entity_id_2: str
    similarity_score: float
    matching_fields: list[str]
    detection_method: str
    requires_human_review: bool = False

    def partition_key(self) -> str:
        return self.entity_id_1


class TrustScoreUpdatedEvent(BaseEvent):
    event_type: EventType = EventType.TRUST_SCORE_UPDATED
    entity_id: str
    entity_type: str
    previous_score: float | None
    new_score: float
    delta: float
    reason: str

    def partition_key(self) -> str:
        return self.entity_id


class GovernanceViolationEvent(BaseEvent):
    event_type: EventType = EventType.GOVERNANCE_VIOLATION
    entity_id: str
    violation_type: str
    severity: str  # low, medium, high, critical
    policy_id: str
    description: str
    auto_remediated: bool = False

    def partition_key(self) -> str:
        return self.entity_id


class LineageCreatedEvent(BaseEvent):
    event_type: EventType = EventType.LINEAGE_CREATED
    source_id: str
    target_id: str
    relationship_type: str
    transformation: str | None = None

    def partition_key(self) -> str:
        return self.source_id


class RemediationAppliedEvent(BaseEvent):
    event_type: EventType = EventType.REMEDIATION_APPLIED
    entity_id: str
    agent_id: str
    action_type: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    human_approved: bool = False

    def partition_key(self) -> str:
        return self.entity_id

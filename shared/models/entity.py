"""
Core entity models shared across all CognitiveMDM services.
Uses Pydantic v2 throughout.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class EntityType(str, Enum):
    CUSTOMER = "customer"
    PRODUCT = "product"
    SUPPLIER = "supplier"
    EMPLOYEE = "employee"
    ASSET = "asset"
    LOCATION = "location"
    ORGANIZATION = "organization"


class EntityStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    MERGED = "merged"
    DEPRECATED = "deprecated"
    QUARANTINED = "quarantined"


class DataSource(BaseModel):
    source_id: str
    source_name: str
    source_type: str  # crm, erp, csv, api, stream
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    raw_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EntityField(BaseModel):
    name: str
    value: Any
    data_type: str
    source: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_pii: bool = False
    lineage: list[str] = Field(default_factory=list)


class TrustScore(BaseModel):
    overall: float = Field(ge=0.0, le=1.0)
    completeness: float = Field(ge=0.0, le=1.0)
    consistency: float = Field(ge=0.0, le=1.0)
    recency: float = Field(ge=0.0, le=1.0)
    source_reliability: float = Field(ge=0.0, le=1.0)
    computed_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("overall", mode="before")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(float(v), 4)


class ResolutionResult(BaseModel):
    golden_record_id: str
    merged_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    method: str  # exact, fuzzy, semantic, llm
    rationale: str | None = None
    resolved_at: datetime = Field(default_factory=datetime.utcnow)


class Entity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_type: EntityType
    status: EntityStatus = EntityStatus.PENDING
    fields: dict[str, EntityField] = Field(default_factory=dict)
    sources: list[DataSource] = Field(default_factory=list)
    trust_score: TrustScore | None = None
    resolution: ResolutionResult | None = None
    tags: list[str] = Field(default_factory=list)
    ontology_classes: list[str] = Field(default_factory=list)
    embedding_id: str | None = None
    graph_node_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"use_enum_values": True}

    def get_field_value(self, name: str) -> Any:
        field = self.fields.get(name)
        return field.value if field else None

    def to_flat_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "status": self.status,
            **{k: v.value for k, v in self.fields.items()},
        }

    @model_validator(mode="after")
    def update_timestamp(self) -> Entity:
        self.updated_at = datetime.utcnow()
        return self


class EntityCreateRequest(BaseModel):
    entity_type: EntityType
    fields: dict[str, Any]
    source: DataSource
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityUpdateRequest(BaseModel):
    fields: dict[str, Any] | None = None
    tags: list[str] | None = None
    status: EntityStatus | None = None
    metadata: dict[str, Any] | None = None


class EntitySearchRequest(BaseModel):
    query: str
    entity_type: EntityType | None = None
    limit: int = Field(default=20, le=100)
    offset: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    semantic: bool = True


class EntitySearchResult(BaseModel):
    entities: list[Entity]
    total: int
    query_time_ms: float
    semantic_used: bool

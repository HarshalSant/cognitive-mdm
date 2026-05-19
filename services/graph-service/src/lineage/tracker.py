"""
Lineage Tracker — records the full provenance and transformation history of entities.
Supports: ingestion, merge, update, schema-alignment, and enrichment operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class LineageOperation(str, Enum):
    INGESTED = "ingested"
    UPDATED = "updated"
    MERGED_INTO = "merged_into"
    MERGED_FROM = "merged_from"
    SPLIT = "split"
    ENRICHED = "enriched"
    SCHEMA_ALIGNED = "schema_aligned"
    PII_MASKED = "pii_masked"
    TRUST_RECALCULATED = "trust_recalculated"
    AUTO_MERGED = "auto_merged"
    HUMAN_APPROVED_MERGE = "human_approved_merge"
    REJECTED_MERGE = "rejected_merge"


@dataclass
class LineageEvent:
    operation: LineageOperation
    entity_id: str
    timestamp: datetime
    actor: str = "system"
    source: str | None = None
    target_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    field_changes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation.value,
            "entity_id": self.entity_id,
            "timestamp": self.timestamp.isoformat(),
            "actor": self.actor,
            "source": self.source,
            "target_ids": self.target_ids,
            "source_ids": self.source_ids,
            "metadata": self.metadata,
            "field_changes": self.field_changes,
        }


class LineageTracker:
    """
    In-memory lineage tracker.
    In production, events are persisted to PostgreSQL lineage table + Neo4j graph.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[LineageEvent]] = {}   # entity_id -> [events]
        self._global: list[LineageEvent] = []

    def record(self, event: LineageEvent) -> None:
        eid = event.entity_id
        if eid not in self._events:
            self._events[eid] = []
        self._events[eid].append(event)
        self._global.append(event)

    def record_ingestion(
        self,
        entity_id: str,
        source: str,
        actor: str = "system",
        metadata: dict | None = None,
    ) -> None:
        self.record(LineageEvent(
            operation=LineageOperation.INGESTED,
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            actor=actor,
            source=source,
            metadata=metadata or {},
        ))

    def record_merge(
        self,
        merged_entity_id: str,
        source_ids: list[str],
        actor: str = "system",
        confidence: float = 0.0,
        method: str = "auto",
    ) -> None:
        self.record(LineageEvent(
            operation=LineageOperation.AUTO_MERGED if method == "auto" else LineageOperation.HUMAN_APPROVED_MERGE,
            entity_id=merged_entity_id,
            timestamp=datetime.now(timezone.utc),
            actor=actor,
            source_ids=source_ids,
            metadata={"confidence": confidence, "method": method},
        ))
        for src_id in source_ids:
            self.record(LineageEvent(
                operation=LineageOperation.MERGED_INTO,
                entity_id=src_id,
                timestamp=datetime.now(timezone.utc),
                actor=actor,
                target_ids=[merged_entity_id],
                metadata={"confidence": confidence},
            ))

    def record_update(
        self,
        entity_id: str,
        field_changes: dict[str, Any],
        actor: str = "system",
        source: str | None = None,
    ) -> None:
        self.record(LineageEvent(
            operation=LineageOperation.UPDATED,
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            actor=actor,
            source=source,
            field_changes=field_changes,
        ))

    def record_enrichment(
        self,
        entity_id: str,
        enriched_fields: list[str],
        method: str,
        actor: str = "system",
    ) -> None:
        self.record(LineageEvent(
            operation=LineageOperation.ENRICHED,
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            actor=actor,
            metadata={"fields": enriched_fields, "method": method},
        ))

    def record_pii_masking(
        self,
        entity_id: str,
        masked_fields: list[str],
        actor: str = "system",
    ) -> None:
        self.record(LineageEvent(
            operation=LineageOperation.PII_MASKED,
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            actor=actor,
            metadata={"masked_fields": masked_fields},
        ))

    def get_lineage(
        self,
        entity_id: str,
        include_upstream: bool = True,
    ) -> list[dict[str, Any]]:
        events = self._events.get(entity_id, [])
        result = [e.to_dict() for e in events]

        if include_upstream:
            for event in events:
                for src_id in event.source_ids:
                    upstream = self._events.get(src_id, [])
                    for ue in upstream:
                        d = ue.to_dict()
                        d["_upstream_of"] = entity_id
                        result.append(d)

        result.sort(key=lambda e: e["timestamp"])
        return result

    def get_provenance_chain(self, entity_id: str) -> list[str]:
        """Trace back the full chain of source entities."""
        chain = [entity_id]
        visited = {entity_id}
        for event in self._events.get(entity_id, []):
            for src_id in event.source_ids:
                if src_id not in visited:
                    visited.add(src_id)
                    chain.append(src_id)
                    chain.extend(
                        s for s in self.get_provenance_chain(src_id)
                        if s not in visited
                    )
        return chain

    def get_downstream(self, entity_id: str) -> list[str]:
        """Find all entities derived from this one."""
        downstream = []
        for events in self._events.values():
            for event in events:
                if entity_id in event.source_ids and event.entity_id not in downstream:
                    downstream.append(event.entity_id)
        return downstream

    def get_global_stats(self) -> dict[str, Any]:
        op_counts: dict[str, int] = {}
        for event in self._global:
            op = event.operation.value
            op_counts[op] = op_counts.get(op, 0) + 1
        return {
            "total_events": len(self._global),
            "entities_tracked": len(self._events),
            "by_operation": op_counts,
        }

    def export_graph(self) -> dict[str, Any]:
        """Export lineage as graph nodes + edges for visualization."""
        nodes, edges = [], []
        seen_nodes: set[str] = set()

        for entity_id, events in self._events.items():
            if entity_id not in seen_nodes:
                nodes.append({"id": entity_id, "type": "entity"})
                seen_nodes.add(entity_id)

            for event in events:
                for src_id in event.source_ids:
                    if src_id not in seen_nodes:
                        nodes.append({"id": src_id, "type": "entity"})
                        seen_nodes.add(src_id)
                    edges.append({
                        "source": src_id,
                        "target": entity_id,
                        "type": event.operation.value,
                        "timestamp": event.timestamp.isoformat(),
                    })

        return {"nodes": nodes, "edges": edges}

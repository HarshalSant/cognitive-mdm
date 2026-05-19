"""
Semantic Reasoning Engine.
Performs multi-hop inference over the ontology graph and entity relationships.

Capabilities:
  - Class hierarchy traversal (find all subclasses / superclasses)
  - Relationship inference (transitive closure of known relationships)
  - Semantic similarity ranking across ontology classes
  - Anomaly detection via embedding distance thresholds
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InferenceResult:
    entity_id: str
    inferred_class: str
    parent_class: str
    confidence: float
    reasoning_chain: list[str] = field(default_factory=list)
    related_classes: list[str] = field(default_factory=list)
    anomaly_flags: list[str] = field(default_factory=list)


class OntologyGraph:
    """In-memory ontology hierarchy for reasoning."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}    # class -> parent
        self._children: dict[str, list[str]] = {}  # class -> [children]
        self._confidence: dict[str, float] = {}    # class -> avg confidence

    def add_class(self, class_name: str, parent: str, confidence: float = 0.8) -> None:
        self._parent[class_name] = parent
        if parent not in self._children:
            self._children[parent] = []
        if class_name not in self._children[parent]:
            self._children[parent].append(class_name)
        self._confidence[class_name] = confidence

    def get_ancestors(self, class_name: str) -> list[str]:
        """Walk up the class hierarchy."""
        ancestors, current = [], class_name
        while current in self._parent:
            current = self._parent[current]
            if current in ancestors:
                break
            ancestors.append(current)
        return ancestors

    def get_descendants(self, class_name: str) -> list[str]:
        """Collect all subclasses recursively."""
        result = []
        stack = list(self._children.get(class_name, []))
        while stack:
            cls = stack.pop()
            result.append(cls)
            stack.extend(self._children.get(cls, []))
        return result

    def get_siblings(self, class_name: str) -> list[str]:
        parent = self._parent.get(class_name)
        if not parent:
            return []
        return [c for c in self._children.get(parent, []) if c != class_name]

    def depth(self, class_name: str) -> int:
        return len(self.get_ancestors(class_name))


class SemanticReasoningEngine:
    """
    Performs ontological reasoning over entity classes.
    Used to infer missing relationships, detect misclassifications,
    and provide explanations for automated decisions.
    """

    def __init__(self) -> None:
        self._ontology = OntologyGraph()
        self._entity_classes: dict[str, str] = {}   # entity_id -> class_name
        self._class_counts: dict[str, int] = {}

    def ingest_ontology_event(
        self, entity_id: str, class_name: str, parent_class: str, confidence: float
    ) -> None:
        self._ontology.add_class(class_name, parent_class, confidence)
        self._entity_classes[entity_id] = class_name
        self._class_counts[class_name] = self._class_counts.get(class_name, 0) + 1

    def reason(self, entity_id: str) -> InferenceResult | None:
        class_name = self._entity_classes.get(entity_id)
        if not class_name:
            return None

        ancestors = self._ontology.get_ancestors(class_name)
        siblings = self._ontology.get_siblings(class_name)
        parent = ancestors[0] if ancestors else "Entity"
        confidence = self._ontology._confidence.get(class_name, 0.5)

        chain = [
            f"Entity {entity_id} classified as {class_name}",
            f"Parent class: {parent}",
        ]
        if siblings:
            chain.append(f"Sibling classes: {', '.join(siblings[:3])}")

        anomalies = []
        if confidence < 0.55:
            anomalies.append("low_confidence_classification")

        # Flag if entity is classified as a leaf class with no peers
        if not siblings and not self._ontology.get_descendants(class_name):
            anomalies.append("isolated_class_assignment")

        return InferenceResult(
            entity_id=entity_id,
            inferred_class=class_name,
            parent_class=parent,
            confidence=confidence,
            reasoning_chain=chain,
            related_classes=siblings[:5],
            anomaly_flags=anomalies,
        )

    def find_similar_entities(
        self,
        entity_id: str,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Find entities in the same or sibling ontology classes."""
        class_name = self._entity_classes.get(entity_id)
        if not class_name:
            return []

        same_class = [
            eid for eid, cls in self._entity_classes.items()
            if cls == class_name and eid != entity_id
        ]
        siblings = self._ontology.get_siblings(class_name)
        sibling_entities = [
            eid for eid, cls in self._entity_classes.items()
            if cls in siblings and eid != entity_id
        ]
        combined = [(eid, 1.0) for eid in same_class] + [(eid, 0.7) for eid in sibling_entities]
        return [{"entity_id": eid, "similarity": sc, "class": self._entity_classes.get(eid)}
                for eid, sc in combined[:top_k]]

    def class_distribution(self) -> dict[str, int]:
        return dict(sorted(self._class_counts.items(), key=lambda x: -x[1]))

    def get_taxonomy_summary(self) -> dict[str, Any]:
        return {
            "total_classes": len(set(self._entity_classes.values())),
            "total_entities_classified": len(self._entity_classes),
            "class_distribution": self.class_distribution(),
            "max_hierarchy_depth": max(
                (self._ontology.depth(c) for c in set(self._entity_classes.values())), default=0
            ),
        }

    def detect_classification_anomalies(self) -> list[dict[str, Any]]:
        """Scan all classified entities for reasoning anomalies."""
        anomalies = []
        for eid in self._entity_classes:
            result = self.reason(eid)
            if result and result.anomaly_flags:
                anomalies.append({
                    "entity_id": eid,
                    "class": result.inferred_class,
                    "flags": result.anomaly_flags,
                    "confidence": result.confidence,
                })
        return anomalies

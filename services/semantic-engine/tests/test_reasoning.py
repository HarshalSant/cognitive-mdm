"""Unit tests for semantic reasoning engine."""

import pytest
from src.reasoning.engine import SemanticReasoningEngine, OntologyGraph


class TestOntologyGraph:
    def setup_method(self):
        self.graph = OntologyGraph()
        self.graph.add_class("PharmaceuticalSupplier", "Supplier", 0.85)
        self.graph.add_class("TechnologySupplier", "Supplier", 0.80)
        self.graph.add_class("LogisticsProvider", "Supplier", 0.75)
        self.graph.add_class("Supplier", "Organization", 0.95)

    def test_get_ancestors(self):
        ancestors = self.graph.get_ancestors("PharmaceuticalSupplier")
        assert "Supplier" in ancestors
        assert "Organization" in ancestors

    def test_get_siblings(self):
        siblings = self.graph.get_siblings("PharmaceuticalSupplier")
        assert "TechnologySupplier" in siblings
        assert "LogisticsProvider" in siblings

    def test_get_descendants(self):
        descendants = self.graph.get_descendants("Supplier")
        assert "PharmaceuticalSupplier" in descendants
        assert "TechnologySupplier" in descendants

    def test_depth(self):
        assert self.graph.depth("PharmaceuticalSupplier") == 2
        assert self.graph.depth("Supplier") == 1


class TestSemanticReasoningEngine:
    def setup_method(self):
        self.engine = SemanticReasoningEngine()
        self.engine.ingest_ontology_event("e1", "PharmaceuticalSupplier", "Supplier", 0.85)
        self.engine.ingest_ontology_event("e2", "TechnologySupplier", "Supplier", 0.80)
        self.engine.ingest_ontology_event("e3", "PharmaceuticalSupplier", "Supplier", 0.88)

    def test_reason_returns_result(self):
        result = self.engine.reason("e1")
        assert result is not None
        assert result.inferred_class == "PharmaceuticalSupplier"
        assert result.parent_class == "Supplier"

    def test_reason_unknown_entity_returns_none(self):
        result = self.engine.reason("nonexistent")
        assert result is None

    def test_find_similar_same_class(self):
        similar = self.engine.find_similar_entities("e1", top_k=10)
        ids = [s["entity_id"] for s in similar]
        assert "e3" in ids  # same class

    def test_class_distribution(self):
        dist = self.engine.class_distribution()
        assert dist.get("PharmaceuticalSupplier", 0) == 2
        assert dist.get("TechnologySupplier", 0) == 1

    def test_taxonomy_summary_keys(self):
        summary = self.engine.get_taxonomy_summary()
        for key in ["total_classes", "total_entities_classified",
                    "class_distribution", "max_hierarchy_depth"]:
            assert key in summary

    def test_low_confidence_flagged_as_anomaly(self):
        self.engine.ingest_ontology_event("e_low", "PharmaceuticalSupplier", "Supplier", 0.40)
        result = self.engine.reason("e_low")
        assert result is not None
        assert "low_confidence_classification" in result.anomaly_flags

"""Unit tests for lineage tracker."""

import pytest
from src.lineage.tracker import LineageTracker, LineageOperation


class TestLineageTracker:
    def setup_method(self):
        self.tracker = LineageTracker()

    def test_record_ingestion(self):
        self.tracker.record_ingestion("e1", source="csv_upload")
        lineage = self.tracker.get_lineage("e1")
        assert len(lineage) == 1
        assert lineage[0]["operation"] == "ingested"

    def test_record_merge(self):
        self.tracker.record_ingestion("e1", source="csv_upload")
        self.tracker.record_ingestion("e2", source="csv_upload")
        self.tracker.record_merge("e3", source_ids=["e1", "e2"], confidence=0.95)
        lineage = self.tracker.get_lineage("e3")
        ops = [e["operation"] for e in lineage]
        assert "auto_merged" in ops

    def test_provenance_chain_traces_back(self):
        self.tracker.record_ingestion("e1", source="csv_upload")
        self.tracker.record_ingestion("e2", source="csv_upload")
        self.tracker.record_merge("e3", source_ids=["e1", "e2"])
        chain = self.tracker.get_provenance_chain("e3")
        assert "e1" in chain or "e2" in chain

    def test_downstream_tracks_derived_entities(self):
        self.tracker.record_ingestion("e1", source="api")
        self.tracker.record_merge("e2", source_ids=["e1"])
        downstream = self.tracker.get_downstream("e1")
        assert "e2" in downstream

    def test_update_recorded(self):
        self.tracker.record_ingestion("e1", source="csv_upload")
        self.tracker.record_update("e1", field_changes={"name": "New Name"})
        lineage = self.tracker.get_lineage("e1")
        ops = [e["operation"] for e in lineage]
        assert "updated" in ops

    def test_pii_masking_recorded(self):
        self.tracker.record_ingestion("e1", source="api")
        self.tracker.record_pii_masking("e1", masked_fields=["email", "ssn"])
        lineage = self.tracker.get_lineage("e1")
        ops = [e["operation"] for e in lineage]
        assert "pii_masked" in ops

    def test_global_stats(self):
        self.tracker.record_ingestion("e1", source="api")
        self.tracker.record_ingestion("e2", source="api")
        self.tracker.record_merge("e3", source_ids=["e1", "e2"])
        stats = self.tracker.get_global_stats()
        assert stats["total_events"] >= 3
        assert "entities_tracked" in stats
        assert "by_operation" in stats

    def test_export_graph_structure(self):
        self.tracker.record_ingestion("e1", source="api")
        self.tracker.record_merge("e2", source_ids=["e1"])
        graph = self.tracker.export_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert any(edge["target"] == "e2" for edge in graph["edges"])

    def test_empty_entity_returns_empty_lineage(self):
        lineage = self.tracker.get_lineage("nonexistent")
        assert lineage == []

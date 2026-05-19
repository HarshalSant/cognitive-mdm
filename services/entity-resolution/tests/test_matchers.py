"""Unit tests for entity resolution matchers."""

import pytest
from src.matchers.fuzzy_matcher import FuzzyMatcher
from src.matchers.semantic_matcher import TFIDFMatcher
from src.scoring.survivorship import SurvivorshipEngine


# ── Fuzzy matcher ──────────────────────────────────────────────────────────

class TestFuzzyMatcher:
    def setup_method(self):
        self.matcher = FuzzyMatcher()

    def test_identical_names_score_1(self):
        score = self.matcher.score({"name": "Acme Corp"}, {"name": "Acme Corp"})
        assert score >= 0.99

    def test_similar_names_above_threshold(self):
        score = self.matcher.score({"name": "Acme Corporation"}, {"name": "Acme Corp"})
        assert score >= 0.75

    def test_unrelated_names_below_threshold(self):
        score = self.matcher.score({"name": "Acme Corp"}, {"name": "Zeta Industries"})
        assert score < 0.60

    def test_email_match_boosts_score(self):
        a = {"name": "Acme Corp", "email": "info@acme.com"}
        b = {"name": "ACME Corp", "email": "info@acme.com"}
        score = self.matcher.score(a, b)
        assert score >= 0.90

    def test_empty_records_return_zero(self):
        score = self.matcher.score({}, {})
        assert score == 0.0

    def test_phone_normalization(self):
        a = {"phone": "+1-800-555-1234"}
        b = {"phone": "800 555 1234"}
        score = self.matcher.score(a, b)
        assert score >= 0.70


# ── TF-IDF semantic matcher ────────────────────────────────────────────────

class TestTFIDFMatcher:
    def setup_method(self):
        self.matcher = TFIDFMatcher()
        self.entities = {
            "e1": {"id": "e1", "entity_type": "customer",
                   "fields": {"name": "Acme Corporation", "city": "Chicago"}},
            "e2": {"id": "e2", "entity_type": "customer",
                   "fields": {"name": "ACME Corp", "city": "Chicago"}},
            "e3": {"id": "e3", "entity_type": "customer",
                   "fields": {"name": "Zeta Industries", "city": "Dallas"}},
        }
        for eid, e in self.entities.items():
            self.matcher.index(eid, e["fields"])

    def test_similar_entities_high_cosine(self):
        score = self.matcher.compute_similarity(
            {"name": "Acme Corporation", "city": "Chicago"},
            {"name": "ACME Corp", "city": "Chicago"},
        )
        assert score > 0.3

    def test_dissimilar_entities_low_cosine(self):
        score = self.matcher.compute_similarity(
            {"name": "Acme Corporation", "city": "Chicago"},
            {"name": "Zeta Industries", "city": "Dallas"},
        )
        assert score < 0.4

    def test_find_similar_returns_results(self):
        hits = self.matcher.find_similar(
            {"name": "Acme Corp"}, "customer", self.entities,
            limit=5, threshold=0.0,
        )
        assert len(hits) > 0

    def test_exclude_ids_respected(self):
        hits = self.matcher.find_similar(
            {"name": "Acme Corporation"}, "customer", self.entities,
            exclude_ids=["e2"], threshold=0.0,
        )
        ids = [h.entity_id for h in hits]
        assert "e2" not in ids

    def test_entity_type_filter(self):
        extra = {
            "s1": {"id": "s1", "entity_type": "supplier",
                   "fields": {"name": "Acme Supplier"}},
        }
        self.matcher.index("s1", extra["s1"]["fields"])
        all_entities = {**self.entities, **extra}
        hits = self.matcher.find_similar(
            {"name": "Acme"}, "customer", all_entities, threshold=0.0,
        )
        ids = [h.entity_id for h in hits]
        assert "s1" not in ids


# ── Survivorship engine ────────────────────────────────────────────────────

class TestSurvivorshipEngine:
    def setup_method(self):
        self.engine = SurvivorshipEngine()

    def test_most_trusted_source_wins(self):
        records = [
            {"source": "csv_upload", "fields": {"name": "Acme", "email": "old@acme.com"}},
            {"source": "salesforce_crm", "fields": {"name": "Acme Corp", "email": "new@acme.com"}},
        ]
        golden = self.engine.create_golden_record("test-id", records)
        assert golden["fields"]["email"] == "new@acme.com"

    def test_most_complete_wins_tie(self):
        records = [
            {"source": "csv_upload", "fields": {"name": "Acme", "phone": "555-1234", "address": "123 Main"}},
            {"source": "csv_upload", "fields": {"name": "Acme Corp"}},
        ]
        golden = self.engine.create_golden_record("test-id", records)
        assert golden["fields"].get("phone") == "555-1234"

    def test_missing_fields_filled_from_secondary(self):
        records = [
            {"source": "salesforce_crm", "fields": {"name": "Acme"}},
            {"source": "csv_upload", "fields": {"name": "Acme", "address": "123 Main St"}},
        ]
        golden = self.engine.create_golden_record("test-id", records)
        assert golden["fields"].get("address") == "123 Main St"

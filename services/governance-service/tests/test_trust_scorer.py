"""Unit tests for the trust scoring engine."""

import pytest
from datetime import datetime, timedelta, timezone
from src.trust.scorer import TrustScorer, TrustScoreResult, _tier


class TestTrustScorer:
    def setup_method(self):
        self.scorer = TrustScorer()

    def test_gold_tier_complete_crm_record(self):
        result = self.scorer.compute(
            entity_id="e1",
            entity_type="customer",
            fields={"name": "Acme Corp", "email": "info@acme.com",
                    "phone": "555-1234", "address": "100 Main"},
            sources=["salesforce_crm"],
            updated_at=datetime.now(timezone.utc),
        )
        assert result.tier == "gold"
        assert result.overall >= 0.85

    def test_unverified_tier_empty_manual_entry(self):
        result = self.scorer.compute(
            entity_id="e2",
            entity_type="customer",
            fields={"name": "Partial Record"},
            sources=["manual_entry"],
            updated_at=datetime.now(timezone.utc) - timedelta(days=400),
        )
        assert result.tier in ("unverified", "bronze")
        assert result.overall < 0.70

    def test_completeness_increases_with_more_fields(self):
        r1 = self.scorer.compute("e1", "customer", {"name": "Acme"},
                                  ["csv_upload"], datetime.now(timezone.utc))
        r2 = self.scorer.compute("e2", "customer",
                                  {"name": "Acme", "email": "a@b.com",
                                   "phone": "555-1234", "address": "100 Main"},
                                  ["csv_upload"], datetime.now(timezone.utc))
        assert r2.completeness > r1.completeness

    def test_recency_degrades_with_age(self):
        r_fresh = self.scorer.compute(
            "e1", "customer", {"name": "X"}, ["api"],
            datetime.now(timezone.utc))
        r_old = self.scorer.compute(
            "e2", "customer", {"name": "X"}, ["api"],
            datetime.now(timezone.utc) - timedelta(days=365))
        assert r_fresh.recency > r_old.recency

    def test_salesforce_beats_manual_entry(self):
        r_sf = self.scorer.compute("e1", "customer", {"name": "X"},
                                    ["salesforce_crm"], datetime.now(timezone.utc))
        r_me = self.scorer.compute("e2", "customer", {"name": "X"},
                                    ["manual_entry"], datetime.now(timezone.utc))
        assert r_sf.source_reliability > r_me.source_reliability

    def test_consistency_perfect_single_source(self):
        result = self.scorer.compute(
            "e1", "customer", {"name": "Acme"},
            ["salesforce_crm"], datetime.now(timezone.utc),
            source_field_sets=[{"name": "Acme"}],
        )
        assert result.consistency == 1.0

    def test_consistency_low_conflicting_sources(self):
        result = self.scorer.compute(
            "e1", "customer", {"name": "Acme"},
            ["salesforce_crm", "csv_upload"], datetime.now(timezone.utc),
            source_field_sets=[
                {"name": "Acme Corporation", "email": "a@acme.com"},
                {"name": "ACME Corp", "email": "b@acme.com"},
            ],
        )
        assert result.consistency < 1.0

    def test_validity_good_email(self):
        result = self.scorer.compute(
            "e1", "customer",
            {"name": "Acme", "email": "valid@example.com"},
            ["api"], datetime.now(timezone.utc))
        assert result.validity > 0.0

    def test_validity_bad_email(self):
        result = self.scorer.compute(
            "e1", "customer",
            {"name": "Acme", "email": "not-an-email"},
            ["api"], datetime.now(timezone.utc))
        assert result.validity < 1.0

    def test_to_dict_has_all_fields(self):
        result = self.scorer.compute(
            "e1", "customer", {"name": "X"},
            ["api"], datetime.now(timezone.utc))
        d = result.to_dict()
        for key in ["entity_id", "overall", "completeness", "consistency",
                    "recency", "source_reliability", "validity", "tier", "computed_at"]:
            assert key in d

    def test_tier_boundaries(self):
        assert _tier(0.90) == "gold"
        assert _tier(0.85) == "gold"
        assert _tier(0.75) == "silver"
        assert _tier(0.70) == "silver"
        assert _tier(0.60) == "bronze"
        assert _tier(0.50) == "bronze"
        assert _tier(0.49) == "unverified"
        assert _tier(0.0) == "unverified"

    def test_anomaly_detection_flags_degradation(self):
        history = [
            self.scorer.compute("e", "customer",
                                 {"name": "Acme", "email": "a@b.com",
                                  "phone": "555", "address": "X"},
                                 ["salesforce_crm"], datetime.now(timezone.utc))
        ] * 3
        degraded = self.scorer.compute(
            "e", "customer", {"name": "Acme"},
            ["manual_entry"],
            datetime.now(timezone.utc) - timedelta(days=300))
        anomalies = self.scorer.detect_trust_anomalies(degraded, history)
        assert len(anomalies) > 0

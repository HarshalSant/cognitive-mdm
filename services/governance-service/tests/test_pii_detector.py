"""Unit tests for PII detector."""

import pytest
from src.pii.detector import PIIDetector


class TestPIIDetector:
    def setup_method(self):
        self.detector = PIIDetector()

    def test_detects_email(self):
        result = self.detector.scan_entity("e1", {"email": "user@example.com"})
        types = [d["pii_type"] for d in result]
        assert "email" in types

    def test_detects_ssn(self):
        result = self.detector.scan_entity("e1", {"info": "SSN is 123-45-6789"})
        types = [d["pii_type"] for d in result]
        assert "ssn" in types

    def test_detects_phone_by_field_name(self):
        result = self.detector.scan_entity("e1", {"phone": "555-867-5309"})
        assert len(result) > 0

    def test_no_pii_clean_record(self):
        result = self.detector.scan_entity("e1", {
            "name": "Acme Corp",
            "category": "Technology",
            "city": "Chicago",
        })
        assert result == []

    def test_detects_credit_card(self):
        result = self.detector.scan_entity("e1", {"payment": "4111111111111111"})
        types = [d["pii_type"] for d in result]
        assert "credit_card" in types

    def test_mask_fields(self):
        fields = {"email": "user@example.com", "name": "Alice"}
        masked = self.detector.mask_fields(fields, ["email"])
        assert masked["email"] != "user@example.com"
        assert masked["name"] == "Alice"

    def test_confidence_above_threshold(self):
        result = self.detector.scan_entity("e1", {"email": "test@test.com"})
        for d in result:
            assert d["confidence"] >= 0.85

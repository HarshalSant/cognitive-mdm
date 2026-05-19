"""Unit tests for ontology generator."""

import pytest
import pytest_asyncio
from src.ontology.generator import OntologyGenerator, infer_class_rule_based


class TestRuleBasedOntology:
    def test_pharma_supplier_detected(self):
        result = infer_class_rule_based(
            "supplier",
            {"name": "MedSupply Corp", "category": "Pharmaceutical"},
        )
        assert "Pharma" in result["class_name"] or result["confidence"] >= 0.55

    def test_tech_company_detected(self):
        result = infer_class_rule_based(
            "customer",
            {"name": "DataDriven Analytics", "category": "Technology"},
        )
        assert "Tech" in result["class_name"] or "Data" in result["class_name"]

    def test_logistics_supplier_detected(self):
        result = infer_class_rule_based(
            "supplier",
            {"name": "LogiPro Logistics", "category": "Logistics"},
        )
        assert "Logist" in result["class_name"] or result["confidence"] >= 0.55

    def test_unknown_entity_gets_default_class(self):
        result = infer_class_rule_based("customer", {"name": "Unknown Co"})
        assert result["class_name"] is not None
        assert result["confidence"] >= 0.50

    def test_returns_required_fields(self):
        result = infer_class_rule_based("supplier", {"name": "Test Supplier"})
        for key in ["class_name", "parent_class", "confidence", "tags", "method"]:
            assert key in result

    def test_confidence_between_0_and_1(self):
        result = infer_class_rule_based("customer", {"name": "Any Company"})
        assert 0.0 <= result["confidence"] <= 1.0


class TestOntologyGenerator:
    def setup_method(self):
        self.gen = OntologyGenerator()

    @pytest.mark.asyncio
    async def test_infer_falls_back_to_rule_based_without_key(self):
        result = await self.gen.infer_ontology_class(
            "supplier",
            {"name": "EcoPackage Solutions", "category": "Packaging"},
        )
        assert result["class_name"] is not None
        assert result["confidence"] > 0

    @pytest.mark.asyncio
    async def test_extract_relationships_returns_list(self):
        rels = await self.gen.extract_relationships(
            {"name": "Acme Corp"}, {"name": "MedSupply"},
            "customer", "supplier",
        )
        assert isinstance(rels, list)
        if rels:
            assert "relationship" in rels[0]

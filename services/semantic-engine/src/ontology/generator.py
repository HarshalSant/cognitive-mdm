"""
Ontology Generator.
Primary:  LLM-powered class inference via Anthropic Claude.
Fallback: Rule-based keyword matching ontology (no API key required).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

# ─── Rule-based fallback ontology ────────────────────────────────────────────

ONTOLOGY_RULES: dict[str, dict[str, list[str]]] = {
    "customer": {
        "PharmaceuticalCompany":  ["pharma", "drug", "biotech", "therapeut", "medic"],
        "TechnologyCompany":      ["tech", "software", "digital", "cloud", "ai", "saas"],
        "RetailCompany":          ["retail", "store", "shop", "consumer", "ecommerce"],
        "HealthcareOrganization": ["hospital", "clinic", "health", "care", "wellness"],
        "FinancialInstitution":   ["bank", "finance", "invest", "capital", "fund", "insur"],
        "ManufacturingCompany":   ["manufactur", "factory", "industrial", "assembl"],
        "LogisticsCompany":       ["logist", "transport", "freight", "cargo", "deliver"],
        "EducationalInstitution": ["universit", "college", "school", "academ", "educat"],
        "GovernmentAgency":       ["govt", "gov", "federal", "municipal", "public sector"],
        "MediaCompany":           ["media", "broadcast", "publish", "content", "entertain"],
    },
    "supplier": {
        "PharmaceuticalSupplier": ["pharma", "medic", "drug", "biotech", "chemical"],
        "TechnologySupplier":     ["tech", "electronics", "hardware", "software", "digital"],
        "LogisticsProvider":      ["logist", "transport", "distribut", "warehouse", "cargo"],
        "ChemicalSupplier":       ["chem", "compound", "reagent", "material", "substanc"],
        "PackagingSupplier":      ["packag", "container", "box", "eco", "wrap"],
        "ManufacturingSupplier":  ["manufactur", "parts", "component", "material", "steel"],
        "DataServicesProvider":   ["data", "analytics", "insight", "intelligence", "bi"],
        "FoodSupplier":           ["food", "beverage", "agri", "farm", "nutrition"],
    },
    "product": {
        "SoftwareProduct":        ["software", "app", "platform", "saas", "api"],
        "HardwareProduct":        ["hardware", "device", "equipment", "machine", "component"],
        "PharmaceuticalProduct":  ["drug", "medicine", "tablet", "injection", "pharma"],
        "ConsumerGood":           ["retail", "consumer", "fmcg", "household"],
        "IndustrialProduct":      ["industrial", "machinery", "tool", "manufactur"],
        "FoodProduct":            ["food", "beverage", "grocery", "nutrition"],
    },
    "employee": {
        "SoftwareEngineer":       ["engineer", "developer", "software", "coding", "backend"],
        "DataScientist":          ["data", "scientist", "ml", "analytics", "statistician"],
        "SalesRepresentative":    ["sales", "account", "revenue", "customer success"],
        "OperationsManager":      ["operations", "ops", "process", "logistics"],
        "HRProfessional":         ["human resources", "hr", "talent", "recruiter"],
        "FinanceAnalyst":         ["finance", "accounting", "analyst", "cfo", "controller"],
        "ExecutiveLeader":        ["ceo", "cto", "vp", "director", "chief", "president"],
    },
}

PARENT_MAP = {
    "customer": "Organization",
    "supplier": "Organization",
    "product": "Product",
    "employee": "Person",
    "asset": "Asset",
}


def _entity_text_for_ontology(entity_type: str, fields: dict[str, Any]) -> str:
    parts = []
    for f in ["name", "full_name", "company_name", "description", "category",
              "industry", "department", "title", "sector"]:
        if v := fields.get(f):
            parts.append(str(v).lower())
    return " ".join(parts)


def infer_class_rule_based(entity_type: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Rule-based ontology class inference — works without any API key."""
    text = _entity_text_for_ontology(entity_type, fields)
    rules = ONTOLOGY_RULES.get(entity_type, {})
    best_class, best_score = None, 0

    for class_name, keywords in rules.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_class = class_name

    if not best_class:
        category = fields.get("category", "")
        if category:
            safe = re.sub(r"[^a-zA-Z0-9]", "", category.title())
            best_class = f"{safe}{entity_type.title()}"
        else:
            best_class = entity_type.title()

    confidence = min(1.0, 0.55 + best_score * 0.10)
    parent = PARENT_MAP.get(entity_type, "Entity")
    tags = list(rules.get(best_class, []))[:4]

    return {
        "class_name": best_class,
        "display_name": re.sub(r"([A-Z])", r" \1", best_class).strip(),
        "description": f"Inferred {entity_type} class based on field patterns",
        "parent_class": parent,
        "confidence": round(confidence, 3),
        "tags": tags,
        "method": "rule_based",
    }


# ─── LLM-backed generator ─────────────────────────────────────────────────────

class OntologyGenerator:
    """
    Ontology inference engine.
    Uses Claude when ANTHROPIC_API_KEY is set; falls back to rule-based matching.
    """

    def __init__(self) -> None:
        self._client = None
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            except ImportError:
                logger.warning("ontology.anthropic_not_installed")

    async def infer_ontology_class(
        self, entity_type: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._client:
            return infer_class_rule_based(entity_type, fields)

        prompt = f"""Given an entity of type '{entity_type}' with these fields:
{json.dumps(fields, indent=2, default=str)}

Infer the most specific semantic ontology class for this entity.
Respond with JSON only:
{{
  "class_name": "PascalCase string, e.g. PharmaceuticalSupplier",
  "display_name": "human readable name",
  "description": "one sentence description",
  "parent_class": "parent class or null",
  "confidence": 0.0-1.0,
  "tags": ["semantic", "tags"],
  "method": "llm"
}}"""

        try:
            import anthropic
            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            logger.warning("ontology.llm_fallback", error=str(e))
            return infer_class_rule_based(entity_type, fields)

    async def extract_relationships(
        self,
        entity_1: dict[str, Any],
        entity_2: dict[str, Any],
        entity_type_1: str,
        entity_type_2: str,
    ) -> list[dict[str, Any]]:
        """Infer semantic relationships between two entities."""
        # Rule-based fallback
        fallback_rels = _infer_relationships_rule(entity_type_1, entity_type_2)

        if not self._client:
            return fallback_rels

        prompt = f"""Two entities:
Entity A ({entity_type_1}): {json.dumps(entity_1, default=str)}
Entity B ({entity_type_2}): {json.dumps(entity_2, default=str)}

What semantic relationships might exist between them?
Respond with JSON array only:
[{{"relationship": "SUPPLIES|LOCATED_IN|BELONGS_TO|MANAGED_BY|PARTNERS_WITH|etc",
   "direction": "A_to_B|B_to_A|bidirectional",
   "confidence": 0.0-1.0,
   "rationale": "brief reason"}}]"""

        try:
            import anthropic
            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            logger.warning("ontology.relationships_fallback", error=str(e))
            return fallback_rels

    async def generate_schema_description(
        self, entity_type: str, sample_fields: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Generate a schema description for an entity type from field samples."""
        if not self._client:
            return _schema_rule_based(entity_type, sample_fields)

        field_summary = {}
        for sample in sample_fields[:5]:
            for k, v in sample.items():
                if k not in field_summary:
                    field_summary[k] = str(v)[:50]

        prompt = f"""Analyze this {entity_type} entity schema:
Fields seen: {json.dumps(field_summary, default=str)}

Respond with JSON:
{{
  "entity_type": "{entity_type}",
  "description": "schema description",
  "required_fields": ["list"],
  "optional_fields": ["list"],
  "pii_fields": ["fields containing PII"],
  "key_identifiers": ["fields used for matching/deduplication"]
}}"""

        try:
            import anthropic
            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            logger.warning("ontology.schema_fallback", error=str(e))
            return _schema_rule_based(entity_type, sample_fields)


def _infer_relationships_rule(type_1: str, type_2: str) -> list[dict]:
    REL_MAP = {
        ("customer", "supplier"): [{"relationship": "SOURCED_FROM", "direction": "A_to_B", "confidence": 0.6, "rationale": "customers procure from suppliers"}],
        ("supplier", "customer"): [{"relationship": "SUPPLIES", "direction": "A_to_B", "confidence": 0.6, "rationale": "supplier provides goods/services to customer"}],
        ("employee", "customer"): [{"relationship": "MANAGES_ACCOUNT", "direction": "A_to_B", "confidence": 0.5, "rationale": "employee may manage customer relationship"}],
        ("product", "supplier"): [{"relationship": "SUPPLIED_BY", "direction": "A_to_B", "confidence": 0.7, "rationale": "product is sourced from supplier"}],
    }
    return REL_MAP.get((type_1, type_2), [{"relationship": "RELATED_TO", "direction": "bidirectional", "confidence": 0.3, "rationale": "general relationship"}])


def _schema_rule_based(entity_type: str, sample_fields: list[dict]) -> dict:
    all_fields = set()
    for s in sample_fields:
        all_fields.update(s.keys())
    pii_names = {"email", "phone", "ssn", "date_of_birth", "contact_email", "mobile"}
    return {
        "entity_type": entity_type,
        "description": f"Schema inferred from {len(sample_fields)} samples",
        "required_fields": list(all_fields)[:4],
        "optional_fields": list(all_fields)[4:],
        "pii_fields": [f for f in all_fields if f in pii_names],
        "key_identifiers": ["name", "email", "tax_id", "contact_email"],
        "method": "rule_based",
    }

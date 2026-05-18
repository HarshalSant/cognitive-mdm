"""
Ontology Generator.
Infers semantic classes, relationships, and taxonomy from entity field patterns.
Uses LLM to generate ontology descriptions and relationships.
"""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
import structlog

logger = structlog.get_logger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")


class OntologyGenerator:
    def __init__(self):
        self._client: anthropic.AsyncAnthropic | None = None
        if ANTHROPIC_API_KEY:
            self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    async def infer_ontology_class(
        self, entity_type: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Infer semantic ontology class for an entity based on its field values.
        Returns class name, description, and parent class suggestions.
        """
        if not self._client:
            return {"class": entity_type.title(), "confidence": 0.5, "parent": None}

        prompt = f"""Given an entity of type '{entity_type}' with these fields:
{json.dumps(fields, indent=2, default=str)}

Infer the most specific semantic ontology class for this entity.
Respond with JSON only:
{{
  "class_name": "string (e.g. 'PharmaceuticalSupplier', 'RetailCustomer')",
  "display_name": "string",
  "description": "string",
  "parent_class": "string or null",
  "confidence": number,
  "tags": ["list", "of", "semantic", "tags"]
}}"""

        try:
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
            logger.error("ontology.infer_failed", error=str(e))
            return {"class_name": entity_type.title(), "confidence": 0.3, "parent_class": None}

    async def extract_relationships(
        self,
        entity_1: dict[str, Any],
        entity_2: dict[str, Any],
        entity_type_1: str,
        entity_type_2: str,
    ) -> list[dict[str, Any]]:
        """Infer semantic relationships between two entities."""
        if not self._client:
            return []

        prompt = f"""Given two entities:
Entity A ({entity_type_1}): {json.dumps(entity_1, default=str)}
Entity B ({entity_type_2}): {json.dumps(entity_2, default=str)}

What semantic relationships might exist between them?
Respond with JSON array:
[
  {{
    "relationship": "SUPPLIES|LOCATED_IN|BELONGS_TO|MANAGED_BY|etc",
    "direction": "A_to_B|B_to_A|bidirectional",
    "confidence": number,
    "rationale": "string"
  }}
]"""

        try:
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
            logger.error("ontology.relationships_failed", error=str(e))
            return []

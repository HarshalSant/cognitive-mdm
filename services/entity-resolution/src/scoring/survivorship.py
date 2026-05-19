"""
Survivorship Engine -- selects the best field value when merging multiple entity records.

Strategy hierarchy (per field):
  1. Custom rule if defined
  2. Highest-trust source wins
  3. Most recent non-null value
  4. Majority vote across sources
  5. Longest non-null value
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Source trust weights (higher = more authoritative)
SOURCE_TRUST: dict[str, float] = {
    "salesforce_crm": 0.95,
    "sap_erp": 0.90,
    "workday_hris": 0.92,
    "api_integration": 0.80,
    "csv_upload": 0.70,
    "manual_entry": 0.60,
}

# Fields that should always take the most recent value
RECENCY_PRIORITY_FIELDS = {
    "status", "last_modified", "last_updated", "email", "phone", "address"
}

# Fields that should take the value from the most trusted source
TRUST_PRIORITY_FIELDS = {
    "name", "full_name", "company_name", "tax_id", "registration_number",
    "date_of_birth", "employee_id", "product_sku",
}


class SurvivorshipEngine:
    """
    Adaptive survivorship logic for golden record construction.
    Field-level winner selection with configurable strategies.
    """

    def compute_golden_record(
        self,
        field_sets: list[dict[str, Any]],
        entity_type: str,
        custom_rules: dict[str, str] | None = None,
        sources: list[str] | None = None,
        timestamps: list[datetime] | None = None,
    ) -> dict[str, Any]:
        """
        Build the golden record by selecting the best value for each field.

        Args:
            field_sets: List of field dicts from each source record.
                        First entry is the incoming entity.
            entity_type: Entity domain for type-specific rules.
            custom_rules: Optional field-level override strategies.
            sources: Source names corresponding to each field_set.
            timestamps: Ingestion timestamps for recency scoring.
        """
        if not field_sets:
            return {}

        sources = sources or ["unknown"] * len(field_sets)
        timestamps = timestamps or [datetime.utcnow()] * len(field_sets)
        custom_rules = custom_rules or {}

        # Collect all unique field names across all records
        all_fields: set[str] = set()
        for fs in field_sets:
            all_fields.update(fs.keys())

        golden: dict[str, Any] = {}
        survivorship_log: dict[str, dict] = {}

        for field_name in all_fields:
            values_with_meta = [
                {
                    "value": fs.get(field_name),
                    "source": sources[i],
                    "trust": SOURCE_TRUST.get(sources[i], 0.5),
                    "timestamp": timestamps[i],
                }
                for i, fs in enumerate(field_sets)
                if fs.get(field_name) is not None
            ]

            if not values_with_meta:
                continue

            strategy = custom_rules.get(field_name) or self._select_strategy(field_name)
            winner = self._apply_strategy(strategy, values_with_meta, field_name)

            golden[field_name] = winner["value"]
            survivorship_log[field_name] = {
                "strategy": strategy,
                "winning_source": winner["source"],
                "confidence": winner["trust"],
            }

        logger.debug("survivorship.golden_record_built", fields=len(golden))
        golden["_survivorship"] = survivorship_log
        return golden

    def _select_strategy(self, field_name: str) -> str:
        if field_name in TRUST_PRIORITY_FIELDS:
            return "trust"
        if field_name in RECENCY_PRIORITY_FIELDS:
            return "recency"
        return "majority"

    def _apply_strategy(
        self,
        strategy: str,
        candidates: list[dict],
        field_name: str,
    ) -> dict:
        if not candidates:
            return {"value": None, "source": "none", "trust": 0.0}

        if strategy == "trust":
            return max(candidates, key=lambda c: c["trust"])

        if strategy == "recency":
            return max(candidates, key=lambda c: c["timestamp"])

        if strategy == "majority":
            value_counts = Counter(
                str(c["value"]) for c in candidates if c["value"] is not None
            )
            if not value_counts:
                return candidates[0]
            majority_value = value_counts.most_common(1)[0][0]
            # Return metadata from the first candidate matching majority value
            for c in candidates:
                if str(c["value"]) == majority_value:
                    return c
            return candidates[0]

        if strategy == "longest":
            return max(candidates, key=lambda c: len(str(c["value"] or "")))

        if strategy == "shortest":
            return min(candidates, key=lambda c: len(str(c["value"] or "")))

        # Default: trust
        return max(candidates, key=lambda c: c["trust"])

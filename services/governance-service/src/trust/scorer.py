"""
Trust Scoring Engine.
Computes a multi-dimensional trust score for each entity.

Dimensions:
  - Completeness: how many expected fields are populated
  - Consistency:  how consistent values are across sources
  - Recency:      how recently the record was updated
  - Source reliability: weighted average trust of originating sources
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SOURCE_TRUST: dict[str, float] = {
    "salesforce_crm": 0.95,
    "sap_erp": 0.90,
    "workday_hris": 0.92,
    "api_integration": 0.80,
    "csv_upload": 0.70,
    "manual_entry": 0.60,
}

REQUIRED_FIELDS_BY_TYPE: dict[str, list[str]] = {
    "customer": ["name", "email", "phone", "address"],
    "product": ["name", "sku", "description", "price"],
    "supplier": ["name", "tax_id", "address", "contact_email"],
    "employee": ["full_name", "email", "department", "hire_date"],
    "asset": ["name", "asset_type", "owner", "location"],
}


@dataclass
class TrustScoreResult:
    entity_id: str
    overall: float
    completeness: float
    consistency: float
    recency: float
    source_reliability: float
    tier: str
    computed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "overall": self.overall,
            "completeness": self.completeness,
            "consistency": self.consistency,
            "recency": self.recency,
            "source_reliability": self.source_reliability,
            "tier": self.tier,
            "computed_at": self.computed_at.isoformat(),
        }


def _tier(score: float) -> str:
    if score >= 0.85:
        return "gold"
    if score >= 0.70:
        return "silver"
    if score >= 0.50:
        return "bronze"
    return "unverified"


class TrustScorer:
    def compute(
        self,
        entity_id: str,
        entity_type: str,
        fields: dict[str, Any],
        sources: list[str],
        updated_at: datetime | None = None,
        source_field_sets: list[dict[str, Any]] | None = None,
    ) -> TrustScoreResult:
        completeness = self._completeness(entity_type, fields)
        consistency = self._consistency(source_field_sets or [fields])
        recency = self._recency(updated_at)
        source_rel = self._source_reliability(sources)

        overall = (
            completeness * 0.30
            + consistency * 0.25
            + recency * 0.20
            + source_rel * 0.25
        )
        overall = round(min(1.0, max(0.0, overall)), 4)

        return TrustScoreResult(
            entity_id=entity_id,
            overall=overall,
            completeness=round(completeness, 4),
            consistency=round(consistency, 4),
            recency=round(recency, 4),
            source_reliability=round(source_rel, 4),
            tier=_tier(overall),
            computed_at=datetime.now(timezone.utc),
        )

    def _completeness(self, entity_type: str, fields: dict[str, Any]) -> float:
        required = REQUIRED_FIELDS_BY_TYPE.get(entity_type, ["name"])
        present = sum(1 for f in required if fields.get(f) not in (None, "", []))
        return present / len(required) if required else 1.0

    def _consistency(self, field_sets: list[dict[str, Any]]) -> float:
        if len(field_sets) <= 1:
            return 1.0
        all_keys = set()
        for fs in field_sets:
            all_keys.update(fs.keys())
        if not all_keys:
            return 1.0
        consistent = 0
        for key in all_keys:
            values = [str(fs.get(key, "")).strip().lower() for fs in field_sets if fs.get(key)]
            unique_values = set(values)
            if len(unique_values) <= 1:
                consistent += 1
        return consistent / len(all_keys)

    def _recency(self, updated_at: datetime | None) -> float:
        if not updated_at:
            return 0.5
        now = datetime.now(timezone.utc)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age_days = (now - updated_at).days
        # Exponential decay: full score within 30 days, ~0.5 at 6 months
        return round(math.exp(-age_days / 180), 4)

    def _source_reliability(self, sources: list[str]) -> float:
        if not sources:
            return 0.5
        weights = [SOURCE_TRUST.get(s, 0.5) for s in sources]
        return sum(weights) / len(weights)

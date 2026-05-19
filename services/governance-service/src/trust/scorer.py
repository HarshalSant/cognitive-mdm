"""
Trust Scoring Engine — Multi-Dimensional ML-style Trust Model.

Dimensions:
  completeness     (0.30) — required fields present and non-empty
  consistency      (0.20) — field values agree across sources
  recency          (0.18) — exponential decay from last update
  source_reliability (0.22) — weighted trust of originating sources
  validity         (0.10) — format correctness of key fields
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SOURCE_TRUST: dict[str, float] = {
    "salesforce_crm":  0.95,
    "sap_erp":         0.90,
    "workday_hris":    0.92,
    "api_integration": 0.80,
    "csv_upload":      0.70,
    "manual_entry":    0.60,
    "merge":           0.85,
    "api":             0.80,
}

REQUIRED_FIELDS_BY_TYPE: dict[str, list[str]] = {
    "customer": ["name", "email", "phone", "address"],
    "product":  ["name", "sku", "description", "price"],
    "supplier": ["name", "tax_id", "address", "contact_email"],
    "employee": ["full_name", "email", "department", "hire_date"],
    "asset":    ["name", "asset_type", "owner", "location"],
}

# Field format validators
_VALIDATORS: dict[str, re.Pattern] = {
    "email":         re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+"),
    "contact_email": re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+"),
    "phone":         re.compile(r"[\+\d\s\-\(\)\.]{7,20}"),
    "tax_id":        re.compile(r".{5,}"),
    "sku":           re.compile(r".{3,}"),
    "zip":           re.compile(r"\d{4,10}"),
}


@dataclass
class TrustScoreResult:
    entity_id: str
    overall: float
    completeness: float
    consistency: float
    recency: float
    source_reliability: float
    validity: float
    tier: str
    computed_at: datetime
    dimension_weights: dict[str, float] = field(default_factory=lambda: {
        "completeness": 0.30,
        "consistency": 0.20,
        "recency": 0.18,
        "source_reliability": 0.22,
        "validity": 0.10,
    })

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "overall": self.overall,
            "completeness": self.completeness,
            "consistency": self.consistency,
            "recency": self.recency,
            "source_reliability": self.source_reliability,
            "validity": self.validity,
            "tier": self.tier,
            "computed_at": self.computed_at.isoformat(),
            "dimension_weights": self.dimension_weights,
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
    """
    Multi-dimensional trust scorer.
    All dimensions are independently computed and weighted.
    """

    DEFAULT_WEIGHTS = {
        "completeness":      0.30,
        "consistency":       0.20,
        "recency":           0.18,
        "source_reliability": 0.22,
        "validity":          0.10,
    }

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or self.DEFAULT_WEIGHTS
        # Normalize weights to sum to 1
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def compute(
        self,
        entity_id: str,
        entity_type: str,
        fields: dict[str, Any],
        sources: list[str],
        updated_at: datetime | None = None,
        source_field_sets: list[dict[str, Any]] | None = None,
    ) -> TrustScoreResult:
        completeness    = self._completeness(entity_type, fields)
        consistency     = self._consistency(source_field_sets or [fields])
        recency         = self._recency(updated_at)
        source_rel      = self._source_reliability(sources)
        validity        = self._validity(fields)

        overall = (
            completeness    * self.weights.get("completeness", 0.30)
            + consistency   * self.weights.get("consistency", 0.20)
            + recency       * self.weights.get("recency", 0.18)
            + source_rel    * self.weights.get("source_reliability", 0.22)
            + validity      * self.weights.get("validity", 0.10)
        )
        overall = round(min(1.0, max(0.0, overall)), 4)

        return TrustScoreResult(
            entity_id=entity_id,
            overall=overall,
            completeness=round(completeness, 4),
            consistency=round(consistency, 4),
            recency=round(recency, 4),
            source_reliability=round(source_rel, 4),
            validity=round(validity, 4),
            tier=_tier(overall),
            computed_at=datetime.now(timezone.utc),
            dimension_weights=self.weights,
        )

    # ── Dimension implementations ──────────────────────────────────────────

    def _completeness(self, entity_type: str, fields: dict[str, Any]) -> float:
        required = REQUIRED_FIELDS_BY_TYPE.get(entity_type, ["name"])
        present = sum(1 for f in required if fields.get(f) not in (None, "", [], {}))
        base = present / len(required) if required else 1.0
        # Bonus: extra fields beyond required (up to 10% bonus)
        total_populated = sum(1 for v in fields.values() if v not in (None, "", [], {}))
        bonus = min(0.10, (total_populated - len(required)) * 0.01)
        return min(1.0, base + max(0.0, bonus))

    def _consistency(self, field_sets: list[dict[str, Any]]) -> float:
        if len(field_sets) <= 1:
            return 1.0
        all_keys: set[str] = set()
        for fs in field_sets:
            all_keys.update(fs.keys())
        if not all_keys:
            return 1.0
        consistent = 0
        for key in all_keys:
            values = [str(fs.get(key, "")).strip().lower()
                      for fs in field_sets if fs.get(key)]
            if len(set(values)) <= 1:
                consistent += 1
        return consistent / len(all_keys)

    def _recency(self, updated_at: datetime | None) -> float:
        if not updated_at:
            return 0.50
        now = datetime.now(timezone.utc)
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - updated_at).days)
        # Fast decay in first 30 days, then slower; full score < 1 day old
        if age_days == 0:
            return 1.0
        return round(math.exp(-age_days / 180), 4)

    def _source_reliability(self, sources: list[str]) -> float:
        if not sources:
            return 0.50
        weights = [SOURCE_TRUST.get(s, 0.50) for s in sources]
        # Best source wins with 70% weight, average with 30%
        best = max(weights)
        avg = sum(weights) / len(weights)
        return round(best * 0.70 + avg * 0.30, 4)

    def _validity(self, fields: dict[str, Any]) -> float:
        if not fields:
            return 0.50
        checks, passed = 0, 0
        for field_name, pattern in _VALIDATORS.items():
            val = fields.get(field_name)
            if val:
                checks += 1
                if pattern.match(str(val).strip()):
                    passed += 1
        if checks == 0:
            return 0.80  # No checkable fields — neutral
        return passed / checks

    # ── Batch scoring ──────────────────────────────────────────────────────

    def compute_batch(
        self,
        entities: list[dict[str, Any]],
    ) -> list[TrustScoreResult]:
        results = []
        for entity in entities:
            eid = entity.get("id", "")
            etype = entity.get("entity_type", "customer")
            fields = entity.get("fields", {})
            sources = [entity.get("source", "csv_upload")]
            updated = None
            if ua := entity.get("updated_at"):
                try:
                    updated = datetime.fromisoformat(ua.replace("Z", "+00:00"))
                except ValueError:
                    pass
            results.append(self.compute(eid, etype, fields, sources, updated))
        return results

    # ── Anomaly detection ─────────────────────────────────────────────────

    def detect_trust_anomalies(
        self,
        current: TrustScoreResult,
        history: list[TrustScoreResult],
    ) -> list[dict[str, Any]]:
        """Flag significant trust score degradations vs historical scores."""
        if not history:
            return []
        anomalies = []
        avg_hist = sum(h.overall for h in history) / len(history)
        delta = current.overall - avg_hist
        if delta < -0.15:
            anomalies.append({
                "type": "trust_degradation",
                "severity": "high" if delta < -0.25 else "medium",
                "delta": round(delta, 4),
                "current": current.overall,
                "historical_avg": round(avg_hist, 4),
                "description": f"Trust score dropped {abs(delta):.1%} vs historical average",
            })
        for dim in ["completeness", "consistency", "recency", "source_reliability", "validity"]:
            hist_dim_avg = sum(getattr(h, dim) for h in history) / len(history)
            curr_dim = getattr(current, dim)
            dim_delta = curr_dim - hist_dim_avg
            if dim_delta < -0.20:
                anomalies.append({
                    "type": f"{dim}_degradation",
                    "severity": "medium",
                    "dimension": dim,
                    "delta": round(dim_delta, 4),
                    "current": curr_dim,
                    "historical_avg": round(hist_dim_avg, 4),
                })
        return anomalies

"""
Policy evaluation engine.
Loads governance policies from the database and evaluates entities against them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = structlog.get_logger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://mdm:mdmpassword@postgres:5432/cognitive_mdm"
)


@dataclass
class PolicyViolation:
    policy_id: str
    policy_name: str
    violation_type: str
    severity: str
    description: str
    auto_remediable: bool = False


class PolicyEngine:
    def __init__(self, policies: list[dict[str, Any]]):
        self._policies = policies

    @classmethod
    async def create(cls) -> "PolicyEngine":
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                result = await session.execute(
                    text("SELECT * FROM governance_policies WHERE is_active = TRUE")
                )
                policies = [dict(r) for r in result.mappings().all()]
                logger.info("policy_engine.loaded", count=len(policies))
                return cls(policies)
        except Exception as e:
            logger.warning("policy_engine.load_failed", error=str(e))
            return cls([])

    def evaluate(
        self,
        entity_id: str,
        entity_type: str,
        fields: dict[str, Any],
        trust_score: float | None = None,
        pii_detections: list | None = None,
    ) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []

        for policy in self._policies:
            applies_to = policy.get("applies_to") or []
            if applies_to and entity_type not in applies_to:
                continue

            rules = policy.get("rules") or {}
            policy_type = policy.get("policy_type", "")

            if policy_type == "quality":
                violations.extend(
                    self._eval_quality(policy, entity_type, fields, rules)
                )
            elif policy_type == "pii" and pii_detections:
                violations.extend(
                    self._eval_pii(policy, entity_type, pii_detections, rules)
                )

        return violations

    def _eval_quality(
        self,
        policy: dict,
        entity_type: str,
        fields: dict[str, Any],
        rules: dict[str, Any],
    ) -> list[PolicyViolation]:
        violations = []

        min_completeness = rules.get("min_completeness", 0.0)
        required_fields: list[str] = rules.get("required_fields", [])

        # Check required fields
        for field in required_fields:
            if not fields.get(field):
                violations.append(
                    PolicyViolation(
                        policy_id=str(policy.get("id", "")),
                        policy_name=policy.get("name", ""),
                        violation_type="missing_required_field",
                        severity=policy.get("severity", "medium"),
                        description=f"Required field '{field}' is missing or empty",
                        auto_remediable=False,
                    )
                )

        return violations

    def _eval_pii(
        self,
        policy: dict,
        entity_type: str,
        pii_detections: list,
        rules: dict[str, Any],
    ) -> list[PolicyViolation]:
        mask_fields: list[str] = rules.get("mask_fields", [])
        violations = []
        for detection in pii_detections:
            field_path = getattr(detection, "field_path", "")
            pii_type = getattr(detection, "pii_type", "")
            if pii_type in mask_fields or field_path in mask_fields:
                violations.append(
                    PolicyViolation(
                        policy_id=str(policy.get("id", "")),
                        policy_name=policy.get("name", ""),
                        violation_type="unmasked_pii",
                        severity="high",
                        description=f"PII field '{field_path}' ({pii_type}) requires masking",
                        auto_remediable=True,
                    )
                )
        return violations

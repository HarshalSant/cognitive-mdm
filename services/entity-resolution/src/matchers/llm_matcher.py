"""
LLM-assisted entity matching using Anthropic Claude.
Used for high-confidence confirmation and complex disambiguation cases
where fuzzy and semantic matching are ambiguous (0.6–0.85 confidence zone).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import anthropic
import structlog

logger = structlog.get_logger(__name__)

LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


@dataclass
class LLMMatchDecision:
    is_duplicate: bool
    confidence: float
    reasoning: str
    matching_evidence: list[str]
    distinguishing_evidence: list[str]
    recommendation: str  # merge, review, reject


SYSTEM_PROMPT = """You are an expert data quality analyst specializing in Master Data Management.
Your task is to determine whether two entity records refer to the same real-world entity.

Analyze the provided records carefully. Consider:
- Name variations (abbreviations, nicknames, legal vs trade names)
- Address formatting differences
- Phone/email formatting variations
- Contextual clues from other fields
- Business vs personal name patterns
- Common data entry errors

Respond ONLY with a valid JSON object in this exact format:
{
  "is_duplicate": boolean,
  "confidence": float (0.0 to 1.0),
  "reasoning": "Brief explanation of your decision",
  "matching_evidence": ["list", "of", "matching", "evidence"],
  "distinguishing_evidence": ["list", "of", "differences"],
  "recommendation": "merge" | "review" | "reject"
}"""


class LLMMatcher:
    """
    Uses Claude to make final determination on ambiguous entity pairs.
    Rate-limited and cached to minimize API costs.
    """

    def __init__(self):
        self._client: anthropic.AsyncAnthropic | None = None
        self._cache: dict[str, LLMMatchDecision] = {}

    def initialize(self) -> None:
        if ANTHROPIC_API_KEY:
            self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            logger.info("llm_matcher.ready", model=LLM_MODEL)
        else:
            logger.warning("llm_matcher.no_api_key", msg="LLM matching disabled")

    def _cache_key(self, fields_1: dict, fields_2: dict) -> str:
        import hashlib
        payload = json.dumps(
            {"a": sorted(fields_1.items()), "b": sorted(fields_2.items())}, sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    async def match(
        self,
        entity_1: dict[str, Any],
        entity_2: dict[str, Any],
        entity_type: str,
        prior_score: float = 0.5,
        context: str = "",
    ) -> LLMMatchDecision:
        """
        Ask Claude to make a definitive match/no-match decision.
        Only called when fuzzy + semantic scores are inconclusive.
        """
        if not self._client:
            return LLMMatchDecision(
                is_duplicate=prior_score >= 0.85,
                confidence=prior_score,
                reasoning="LLM matching unavailable — using prior score",
                matching_evidence=[],
                distinguishing_evidence=[],
                recommendation="review" if 0.6 <= prior_score < 0.85 else (
                    "merge" if prior_score >= 0.85 else "reject"
                ),
            )

        cache_key = self._cache_key(entity_1, entity_2)
        if cache_key in self._cache:
            logger.debug("llm_matcher.cache_hit", key=cache_key)
            return self._cache[cache_key]

        user_message = f"""Compare these two {entity_type} records and determine if they represent the same real-world entity.

Prior similarity score from automated matching: {prior_score:.2f}
{f"Additional context: {context}" if context else ""}

Record A:
{json.dumps(entity_1, indent=2, default=str)}

Record B:
{json.dumps(entity_2, indent=2, default=str)}

Respond with the JSON analysis."""

        try:
            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            raw = response.content[0].text.strip()
            # Strip markdown code blocks if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)

            decision = LLMMatchDecision(
                is_duplicate=bool(data["is_duplicate"]),
                confidence=float(data["confidence"]),
                reasoning=str(data["reasoning"]),
                matching_evidence=list(data.get("matching_evidence", [])),
                distinguishing_evidence=list(data.get("distinguishing_evidence", [])),
                recommendation=str(data.get("recommendation", "review")),
            )

            self._cache[cache_key] = decision
            logger.info(
                "llm_matcher.decision",
                is_duplicate=decision.is_duplicate,
                confidence=decision.confidence,
                recommendation=decision.recommendation,
            )
            return decision

        except Exception as e:
            logger.error("llm_matcher.error", error=str(e))
            return LLMMatchDecision(
                is_duplicate=prior_score >= 0.85,
                confidence=prior_score * 0.8,
                reasoning=f"LLM matching failed: {e}",
                matching_evidence=[],
                distinguishing_evidence=[],
                recommendation="review",
            )

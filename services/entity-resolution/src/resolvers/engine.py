"""
Core Resolution Engine -- orchestrates multi-stage entity deduplication.

Pipeline:
  1. Blocking (candidate generation via inverted index / LSH)
  2. Exact matching (deterministic field comparison)
  3. Fuzzy matching (Jaro-Winkler, token sort, phonetic)
  4. Semantic matching (vector similarity via Qdrant)
  5. LLM disambiguation (Anthropic Claude for ambiguous cases)
  6. Survivorship (golden record field selection)
  7. Kafka event emission
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog
from prometheus_client import Counter, Histogram

from ..matchers.fuzzy_matcher import FuzzyMatcher
from ..matchers.llm_matcher import LLMMatcher
from ..matchers.semantic_matcher import SemanticMatcher
from ..scoring.confidence import ConfidenceScorer
from ..scoring.survivorship import SurvivorshipEngine

logger = structlog.get_logger(__name__)

MATCHES_FOUND = Counter("entity_resolution_matches_total", "Duplicate pairs found", ["method"])
RESOLUTION_TIME = Histogram(
    "entity_resolution_duration_seconds", "Time to resolve an entity", ["stage"]
)


@dataclass
class ResolutionCandidate:
    entity_id: str
    fields: dict[str, Any]
    source: str
    confidence: float
    method: str
    rationale: str = ""
    matching_fields: list[str] = field(default_factory=list)


@dataclass
class ResolutionResult:
    entity_id: str
    golden_record_id: str
    candidates: list[ResolutionCandidate]
    is_new_golden: bool
    survivorship_map: dict[str, Any]
    overall_confidence: float
    method: str
    reasoning: str
    resolved_at: datetime = field(default_factory=datetime.utcnow)


# Thresholds for decision making
AUTO_MERGE_THRESHOLD = 0.95
HUMAN_REVIEW_THRESHOLD = 0.75
LLM_TRIGGER_THRESHOLD = 0.60  # Use LLM when score is in this ambiguous zone


class ResolutionEngine:
    """
    Multi-stage entity resolution pipeline.
    Combines blocking, fuzzy, semantic, and LLM matching with
    confidence scoring and adaptive survivorship.
    """

    def __init__(self):
        self.fuzzy = FuzzyMatcher()
        self.semantic = SemanticMatcher()
        self.llm = LLMMatcher()
        self.confidence_scorer = ConfidenceScorer()
        self.survivorship = SurvivorshipEngine()
        self._initialized = False

    async def initialize(self) -> None:
        await self.semantic.initialize()
        self.llm.initialize()
        self._initialized = True
        logger.info("resolution_engine.initialized")

    async def resolve_entity(
        self,
        entity_id: str,
        entity_type: str,
        fields: dict[str, Any],
        existing_entities: list[dict[str, Any]],
        threshold: float = HUMAN_REVIEW_THRESHOLD,
        use_llm: bool = True,
    ) -> ResolutionResult:
        """
        Full resolution pipeline for a single entity against a candidate pool.
        """
        candidates: list[ResolutionCandidate] = []

        # Stage 1: Semantic ANN search for candidate blocking
        with RESOLUTION_TIME.labels(stage="semantic").time():
            semantic_matches = await self.semantic.find_similar(
                entity_type=entity_type,
                fields=fields,
                limit=50,
                threshold=0.60,
                exclude_ids=[entity_id],
            )

        # Reduce to entities that exist in our pool
        existing_by_id = {e["id"]: e for e in existing_entities}
        candidate_ids = {m.entity_id for m in semantic_matches if m.entity_id in existing_by_id}

        # Stage 2: Fuzzy matching on candidates
        with RESOLUTION_TIME.labels(stage="fuzzy").time():
            for candidate_id in candidate_ids:
                candidate_fields = existing_by_id[candidate_id].get("fields", {})
                fuzzy_result = self.fuzzy.match(fields, candidate_fields)

                raw_score = (
                    fuzzy_result.overall_score * 0.5
                    + next(
                        (m.score for m in semantic_matches if m.entity_id == candidate_id), 0.0
                    ) * 0.5
                )

                if raw_score < 0.40:
                    continue

                # Stage 3: LLM disambiguation for borderline cases
                final_score = raw_score
                rationale = f"fuzzy={fuzzy_result.overall_score:.2f}"
                method = "fuzzy+semantic"

                if use_llm and LLM_TRIGGER_THRESHOLD <= raw_score < AUTO_MERGE_THRESHOLD:
                    with RESOLUTION_TIME.labels(stage="llm").time():
                        llm_decision = await self.llm.match(
                            entity_1=fields,
                            entity_2=candidate_fields,
                            entity_type=entity_type,
                            prior_score=raw_score,
                        )
                    # Blend LLM confidence with prior score
                    final_score = raw_score * 0.4 + llm_decision.confidence * 0.6
                    rationale = f"fuzzy={fuzzy_result.overall_score:.2f}, llm={llm_decision.confidence:.2f}: {llm_decision.reasoning}"
                    method = "fuzzy+semantic+llm"

                if final_score >= threshold:
                    matching_fields = self.fuzzy.get_matching_fields(fuzzy_result)
                    candidates.append(
                        ResolutionCandidate(
                            entity_id=candidate_id,
                            fields=candidate_fields,
                            source=existing_by_id[candidate_id].get("source", "unknown"),
                            confidence=final_score,
                            method=method,
                            rationale=rationale,
                            matching_fields=matching_fields,
                        )
                    )
                    MATCHES_FOUND.labels(method=method).inc()

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        # Stage 4: Survivorship -- build golden record
        if candidates and candidates[0].confidence >= AUTO_MERGE_THRESHOLD:
            # High confidence -- compute golden record
            all_field_sets = [fields] + [c.fields for c in candidates[:5]]
            survivorship_map = self.survivorship.compute_golden_record(
                field_sets=all_field_sets,
                entity_type=entity_type,
            )
            golden_id = candidates[0].entity_id
            is_new = False
            overall_confidence = candidates[0].confidence
            reasoning = f"Auto-merged: {candidates[0].rationale}"
        else:
            # No high-confidence match -- this entity becomes its own golden record
            survivorship_map = fields
            golden_id = entity_id
            is_new = True
            overall_confidence = 0.0
            reasoning = "No high-confidence duplicates found"

        return ResolutionResult(
            entity_id=entity_id,
            golden_record_id=golden_id,
            candidates=candidates,
            is_new_golden=is_new,
            survivorship_map=survivorship_map,
            overall_confidence=overall_confidence,
            method=candidates[0].method if candidates else "none",
            reasoning=reasoning,
        )

    async def score_pair(
        self,
        entity_id_1: str,
        fields_1: dict[str, Any],
        entity_id_2: str,
        fields_2: dict[str, Any],
        entity_type: str,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        """Score a specific entity pair across all methods."""
        fuzzy_result = self.fuzzy.match(fields_1, fields_2)
        semantic_score = await self.semantic.compute_similarity(fields_1, fields_2)
        combined = fuzzy_result.overall_score * 0.5 + semantic_score * 0.5

        result = {
            "entity_id_1": entity_id_1,
            "entity_id_2": entity_id_2,
            "fuzzy_score": fuzzy_result.overall_score,
            "semantic_score": semantic_score,
            "combined_score": combined,
            "field_scores": [
                {"field": fs.field, "score": fs.score, "method": fs.method}
                for fs in fuzzy_result.field_scores
            ],
            "matching_fields": self.fuzzy.get_matching_fields(fuzzy_result),
        }

        if use_llm and LLM_TRIGGER_THRESHOLD <= combined < AUTO_MERGE_THRESHOLD:
            llm_decision = await self.llm.match(
                fields_1, fields_2, entity_type, prior_score=combined
            )
            result["llm_decision"] = {
                "is_duplicate": llm_decision.is_duplicate,
                "confidence": llm_decision.confidence,
                "reasoning": llm_decision.reasoning,
                "recommendation": llm_decision.recommendation,
            }
            result["final_score"] = combined * 0.4 + llm_decision.confidence * 0.6
        else:
            result["final_score"] = combined

        result["is_duplicate"] = result["final_score"] >= AUTO_MERGE_THRESHOLD
        result["recommendation"] = (
            "auto_merge" if result["final_score"] >= AUTO_MERGE_THRESHOLD
            else "review" if result["final_score"] >= HUMAN_REVIEW_THRESHOLD
            else "reject"
        )

        return result

    async def index_entity(
        self, entity_id: str, entity_type: str, fields: dict[str, Any]
    ) -> None:
        """Index a new entity into the vector store."""
        await self.semantic.index_entity(entity_id, entity_type, fields)

    async def close(self) -> None:
        await self.semantic.close()

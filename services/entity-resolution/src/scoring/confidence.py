"""
Confidence scoring model for entity resolution decisions.
Combines multiple signal sources into a calibrated confidence score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ConfidenceBreakdown:
    fuzzy_contribution: float
    semantic_contribution: float
    llm_contribution: float
    field_overlap_bonus: float
    source_penalty: float
    final_score: float


class ConfidenceScorer:
    """
    Calibrated confidence scoring for match decisions.
    Weights are learned from labeled ground truth in production.
    """

    # Weight distribution (must sum to 1.0)
    FUZZY_WEIGHT = 0.30
    SEMANTIC_WEIGHT = 0.35
    LLM_WEIGHT = 0.35

    def compute(
        self,
        fuzzy_score: float,
        semantic_score: float,
        llm_score: float | None,
        matching_field_count: int,
        total_field_count: int,
        same_source: bool = False,
    ) -> ConfidenceBreakdown:
        """
        Compute calibrated confidence score.

        Args:
            fuzzy_score: Weighted fuzzy match score [0, 1]
            semantic_score: Vector cosine similarity [0, 1]
            llm_score: LLM confidence, None if not used
            matching_field_count: Fields with high similarity
            total_field_count: Total comparable fields
            same_source: Records from same source (slight penalty -- likely already deduped there)
        """
        if llm_score is not None:
            base = (
                fuzzy_score * self.FUZZY_WEIGHT
                + semantic_score * self.SEMANTIC_WEIGHT
                + llm_score * self.LLM_WEIGHT
            )
        else:
            # Redistribute LLM weight
            w_f = self.FUZZY_WEIGHT / (self.FUZZY_WEIGHT + self.SEMANTIC_WEIGHT)
            w_s = self.SEMANTIC_WEIGHT / (self.FUZZY_WEIGHT + self.SEMANTIC_WEIGHT)
            base = fuzzy_score * w_f + semantic_score * w_s

        # Bonus for high field overlap
        field_ratio = matching_field_count / max(total_field_count, 1)
        field_bonus = field_ratio * 0.05  # up to +5%

        # Penalty when records come from same source
        source_penalty = 0.03 if same_source else 0.0

        final = min(1.0, max(0.0, base + field_bonus - source_penalty))

        return ConfidenceBreakdown(
            fuzzy_contribution=fuzzy_score * (self.FUZZY_WEIGHT if llm_score is None else 0.3),
            semantic_contribution=semantic_score * (self.SEMANTIC_WEIGHT if llm_score is None else 0.35),
            llm_contribution=(llm_score or 0.0) * self.LLM_WEIGHT,
            field_overlap_bonus=field_bonus,
            source_penalty=source_penalty,
            final_score=round(final, 4),
        )

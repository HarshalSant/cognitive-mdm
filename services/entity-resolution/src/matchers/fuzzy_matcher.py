"""
Fuzzy string matching for entity fields.
Implements Jaro-Winkler, token sort, phonetic matching, and custom field rules.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import jellyfish
from rapidfuzz import fuzz, process


@dataclass
class FieldMatch:
    field: str
    score: float
    method: str
    value_1: Any
    value_2: Any


@dataclass
class FuzzyMatchResult:
    overall_score: float
    field_scores: list[FieldMatch]
    method: str = "fuzzy"


# Field-specific matching strategies
FIELD_STRATEGIES: dict[str, str] = {
    "name": "jaro_winkler",
    "full_name": "jaro_winkler",
    "company_name": "token_sort",
    "email": "exact_normalized",
    "phone": "phone_normalized",
    "address": "token_partial",
    "city": "jaro_winkler",
    "country": "exact_normalized",
    "tax_id": "exact_normalized",
    "registration_number": "exact_normalized",
    "sku": "exact_normalized",
    "description": "token_sort",
}

# Field weights for overall score computation
FIELD_WEIGHTS: dict[str, float] = {
    "email": 0.30,
    "tax_id": 0.25,
    "phone": 0.20,
    "name": 0.15,
    "full_name": 0.15,
    "company_name": 0.15,
    "address": 0.10,
    "city": 0.05,
}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", str(phone))


def normalize_email(email: str) -> str:
    return normalize_text(email).lower()


def match_field(value1: Any, value2: Any, strategy: str) -> float:
    if value1 is None or value2 is None:
        return 0.0
    s1, s2 = str(value1), str(value2)

    if strategy == "exact_normalized":
        return 1.0 if normalize_text(s1) == normalize_text(s2) else 0.0

    if strategy == "phone_normalized":
        p1, p2 = normalize_phone(s1), normalize_phone(s2)
        if not p1 or not p2:
            return 0.0
        if p1 == p2:
            return 1.0
        # Allow suffix match (last 10 digits)
        return 1.0 if p1[-10:] == p2[-10:] else 0.0

    if strategy == "jaro_winkler":
        return jellyfish.jaro_winkler_similarity(normalize_text(s1), normalize_text(s2))

    if strategy == "token_sort":
        return fuzz.token_sort_ratio(normalize_text(s1), normalize_text(s2)) / 100.0

    if strategy == "token_partial":
        return fuzz.partial_token_sort_ratio(normalize_text(s1), normalize_text(s2)) / 100.0

    if strategy == "phonetic":
        code1 = jellyfish.soundex(s1)
        code2 = jellyfish.soundex(s2)
        return 1.0 if code1 == code2 else 0.5 if code1[0] == code2[0] else 0.0

    # Default: levenshtein ratio
    return fuzz.ratio(normalize_text(s1), normalize_text(s2)) / 100.0


class FuzzyMatcher:
    """
    Multi-field fuzzy matching with field-level strategies and weighted scoring.
    """

    def match(
        self,
        entity_1: dict[str, Any],
        entity_2: dict[str, Any],
        fields: list[str] | None = None,
    ) -> FuzzyMatchResult:
        """
        Score two entity field dicts using fuzzy matching.
        Returns weighted overall score and per-field breakdown.
        """
        target_fields = fields or list(FIELD_WEIGHTS.keys())
        field_scores = []
        weighted_sum = 0.0
        total_weight = 0.0

        for field in target_fields:
            v1 = entity_1.get(field)
            v2 = entity_2.get(field)

            if v1 is None and v2 is None:
                continue

            strategy = FIELD_STRATEGIES.get(field, "jaro_winkler")
            score = match_field(v1, v2, strategy)
            weight = FIELD_WEIGHTS.get(field, 0.05)

            field_scores.append(
                FieldMatch(field=field, score=score, method=strategy, value_1=v1, value_2=v2)
            )
            weighted_sum += score * weight
            total_weight += weight

        overall = weighted_sum / total_weight if total_weight > 0 else 0.0

        return FuzzyMatchResult(
            overall_score=round(overall, 4),
            field_scores=field_scores,
        )

    def get_matching_fields(
        self,
        result: FuzzyMatchResult,
        threshold: float = 0.85,
    ) -> list[str]:
        return [fs.field for fs in result.field_scores if fs.score >= threshold]

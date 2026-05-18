"""
PII Detection engine using regex patterns + optional Presidio/spaCy.
Identifies and classifies personally identifiable information in entity fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class PIIDetection:
    field_path: str
    pii_type: str
    confidence: float
    sample: str  # Masked snippet for audit


# Regex patterns per PII type
PII_PATTERNS: dict[str, tuple[re.Pattern, float]] = {
    "email": (
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I),
        0.99,
    ),
    "phone_us": (
        re.compile(r"(\+1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}"),
        0.90,
    ),
    "ssn": (
        re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"),
        0.95,
    ),
    "credit_card": (
        re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"),
        0.98,
    ),
    "date_of_birth": (
        re.compile(r"\b(0?[1-9]|1[0-2])[-/](0?[1-9]|[12][0-9]|3[01])[-/](19|20)\d{2}\b"),
        0.75,
    ),
    "ip_address": (
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        0.85,
    ),
    "passport": (
        re.compile(r"\b[A-Z]{1,2}[0-9]{6,9}\b"),
        0.70,
    ),
}

# Field names that semantically indicate PII
PII_FIELD_NAMES: dict[str, str] = {
    "email": "email",
    "email_address": "email",
    "phone": "phone",
    "phone_number": "phone",
    "mobile": "phone",
    "ssn": "ssn",
    "social_security": "ssn",
    "dob": "date_of_birth",
    "date_of_birth": "date_of_birth",
    "birth_date": "date_of_birth",
    "passport_number": "passport",
    "credit_card": "credit_card",
    "card_number": "credit_card",
    "ip": "ip_address",
    "ip_address": "ip_address",
}


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


class PIIDetector:
    def scan_entity(
        self,
        entity_id: str,
        fields: dict[str, Any],
    ) -> list[PIIDetection]:
        detections: list[PIIDetection] = []

        for field_name, value in fields.items():
            if value is None:
                continue
            str_value = str(value)

            # Check field name semantics
            if pii_type := PII_FIELD_NAMES.get(field_name.lower()):
                detections.append(
                    PIIDetection(
                        field_path=field_name,
                        pii_type=pii_type,
                        confidence=0.95,
                        sample=_mask(str_value),
                    )
                )
                continue

            # Pattern scan on value
            for pii_type, (pattern, confidence) in PII_PATTERNS.items():
                if pattern.search(str_value):
                    detections.append(
                        PIIDetection(
                            field_path=field_name,
                            pii_type=pii_type,
                            confidence=confidence,
                            sample=_mask(str_value),
                        )
                    )
                    break  # One detection per field

        return detections

    def mask_fields(
        self,
        fields: dict[str, Any],
        detections: list[PIIDetection],
    ) -> dict[str, Any]:
        """Return a copy of fields with PII values masked."""
        masked = dict(fields)
        pii_fields = {d.field_path for d in detections}
        for field in pii_fields:
            if field in masked and masked[field]:
                masked[field] = _mask(str(masked[field]))
        return masked

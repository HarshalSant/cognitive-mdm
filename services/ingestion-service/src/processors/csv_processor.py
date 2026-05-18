"""
CSV ingestion processor.
Reads CSV content, normalises column names, and maps to entity fields.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime
from typing import Any


def normalise_column(col: str) -> str:
    return re.sub(r"\W+", "_", col.strip().lower()).strip("_")


def process_csv(
    content: bytes,
    entity_type: str,
    source_name: str,
) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    records = []

    for row in reader:
        fields = {normalise_column(k): v.strip() for k, v in row.items() if v and v.strip()}
        if not fields:
            continue

        records.append({
            "id": str(uuid.uuid4()),
            "entity_type": entity_type,
            "fields": fields,
            "source": source_name,
            "ingested_at": datetime.utcnow().isoformat(),
        })

    return records

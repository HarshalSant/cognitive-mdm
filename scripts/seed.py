#!/usr/bin/env python3
"""
Seed script — loads sample CSV data into CognitiveMDM via the ingestion API.
Run: python scripts/seed.py
"""

import csv
import json
import os
import sys
import urllib.request
import urllib.error

API_URL = os.environ.get("API_URL", "http://localhost:8001")
SAMPLES = [
    ("data/samples/customers.csv", "customer", "csv_upload"),
    ("data/samples/suppliers.csv", "supplier", "csv_upload"),
]


def post_batch(records: list[dict], entity_type: str, source_name: str) -> None:
    payload = json.dumps({
        "records": records,
        "entity_type": entity_type,
        "source_name": source_name,
    }).encode()

    req = urllib.request.Request(
        f"{API_URL}/ingestion/batch",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)
            print(f"  ✓ {entity_type}: {result.get('processed', 0)} records ingested")
    except urllib.error.URLError as e:
        print(f"  ✗ Failed to ingest {entity_type}: {e}")


def load_csv(path: str) -> list[dict]:
    records = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean = {k.strip(): v.strip() for k, v in row.items() if v and v.strip()}
            records.append(clean)
    return records


def main() -> None:
    print("CognitiveMDM — Seeding sample data")
    print(f"API: {API_URL}\n")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for csv_path, entity_type, source in SAMPLES:
        full_path = os.path.join(root, csv_path)
        if not os.path.exists(full_path):
            print(f"  ✗ File not found: {full_path}")
            continue
        records = load_csv(full_path)
        print(f"Loading {len(records)} {entity_type} records from {csv_path}...")
        post_batch(records, entity_type, source)

    print("\nSeeding complete.")


if __name__ == "__main__":
    main()

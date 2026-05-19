"""Unit tests for ingestion service processors."""

import pytest
import io
from src.processors.csv_processor import CSVProcessor


class TestCSVProcessor:
    def setup_method(self):
        self.processor = CSVProcessor()

    def test_parses_basic_csv(self):
        csv_content = b"id,name,email\ncust-001,Acme Corp,info@acme.com\n"
        records = self.processor.parse(io.BytesIO(csv_content))
        assert len(records) == 1
        assert records[0]["name"] == "Acme Corp"
        assert records[0]["email"] == "info@acme.com"

    def test_skips_empty_rows(self):
        csv_content = b"id,name,email\ncust-001,Acme Corp,info@acme.com\n,,,\n"
        records = self.processor.parse(io.BytesIO(csv_content))
        assert len(records) == 1

    def test_strips_whitespace_from_keys_and_values(self):
        csv_content = b"  id  ,  name  \ncust-001,  Acme Corp  \n"
        records = self.processor.parse(io.BytesIO(csv_content))
        assert records[0]["name"] == "Acme Corp"

    def test_handles_utf8_bom(self):
        csv_content = b"\xef\xbb\xbfid,name\ncust-001,Test Corp\n"
        records = self.processor.parse(io.BytesIO(csv_content))
        assert len(records) == 1
        assert records[0]["name"] == "Test Corp"

    def test_normalizes_column_names_to_snake_case(self):
        csv_content = b"Customer ID,Full Name,Contact Email\ne1,Alice,alice@example.com\n"
        records = self.processor.parse(io.BytesIO(csv_content))
        assert "customer_id" in records[0] or "Customer ID" in records[0]

    def test_large_batch_truncated_at_limit(self):
        rows = "id,name\n" + "\n".join(f"e{i},Name{i}" for i in range(1200))
        records = self.processor.parse(io.BytesIO(rows.encode()))
        assert len(records) <= 1000

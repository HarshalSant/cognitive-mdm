"""Unit tests for GraphRAG retrieval engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.retrieval.rag import GraphRAGRetriever, RetrievedContext, _summarize_fields


class TestRetrievedContext:
    def test_to_prompt_context_empty(self):
        ctx = RetrievedContext(query="test")
        prompt = ctx.to_prompt_context()
        assert "test" in prompt

    def test_to_prompt_context_with_entities(self):
        ctx = RetrievedContext(
            query="find duplicates",
            entities=[
                {"id": "e1", "entity_type": "customer",
                 "fields": {"name": "Acme Corp", "city": "Chicago"}},
            ],
        )
        prompt = ctx.to_prompt_context()
        assert "Acme Corp" in prompt
        assert "customer" in prompt

    def test_to_prompt_context_limits_entities(self):
        ctx = RetrievedContext(
            query="test",
            entities=[{"id": f"e{i}", "entity_type": "customer",
                       "fields": {"name": f"Company {i}"}} for i in range(20)],
        )
        prompt = ctx.to_prompt_context(max_entities=5)
        assert prompt.count("Company") <= 5


class TestSummarizeFields:
    def test_limits_to_3_pairs(self):
        fields = {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"}
        result = _summarize_fields(fields)
        assert result.count("=") <= 3

    def test_skips_system_fields(self):
        fields = {"id": "e1", "created_at": "2024-01-01", "name": "Acme"}
        result = _summarize_fields(fields)
        assert "id" not in result
        assert "name=Acme" in result


class TestGraphRAGRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_returns_context(self):
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: {"entities": [
                {"id": "e1", "entity_type": "customer",
                 "fields": {"name": "Acme Corp"}}
            ]}
        ))
        mock_http.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=lambda: {"nodes": [], "edges": [], "violations": []}
        ))
        retriever = GraphRAGRetriever(http_client=mock_http)
        ctx = await retriever.retrieve("find duplicates", top_k=5)
        assert isinstance(ctx, RetrievedContext)
        assert ctx.total_retrieved >= 0

    @pytest.mark.asyncio
    async def test_retrieve_handles_service_error(self):
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=Exception("connection refused"))
        mock_http.get = AsyncMock(side_effect=Exception("connection refused"))
        retriever = GraphRAGRetriever(http_client=mock_http)
        ctx = await retriever.retrieve("test query")
        assert ctx.entities == []
        assert ctx.total_retrieved == 0

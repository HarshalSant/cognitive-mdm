"""Unit tests for agent service."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.agents.registry import AgentRegistry


@pytest.fixture
def mock_http():
    client = AsyncMock()
    client.get = AsyncMock(return_value=MagicMock(
        status_code=200,
        json=lambda: {"entities": [], "total": 0},
    ))
    client.post = AsyncMock(return_value=MagicMock(
        status_code=200,
        json=lambda: {"processed": 0},
    ))
    return client


class TestAgentRegistry:
    @pytest.mark.asyncio
    async def test_registry_initializes_all_agents(self, mock_http):
        registry = AgentRegistry()
        with patch("httpx.AsyncClient", return_value=mock_http):
            await registry.initialize()
        assert "duplicate_remediator" in registry.agents
        assert "trust_recalculator" in registry.agents
        assert "pii_scanner" in registry.agents
        assert "metadata_enricher" in registry.agents

    @pytest.mark.asyncio
    async def test_get_unknown_agent_raises(self, mock_http):
        registry = AgentRegistry()
        with patch("httpx.AsyncClient", return_value=mock_http):
            await registry.initialize()
        with pytest.raises(KeyError):
            registry.get("nonexistent_agent")

    @pytest.mark.asyncio
    async def test_get_known_agent_returns_instance(self, mock_http):
        registry = AgentRegistry()
        with patch("httpx.AsyncClient", return_value=mock_http):
            await registry.initialize()
        agent = registry.get("duplicate_remediator")
        assert agent is not None


class TestMDMAgent:
    @pytest.mark.asyncio
    async def test_run_without_api_key_returns_error(self):
        from src.agents.langgraph_agent import MDMAgent
        agent = MDMAgent()
        result = await agent.run("Find duplicates", {})
        assert result.get("complete") is False
        assert "error" in result or "LLM" in str(result)

    def test_agent_state_initialization(self):
        from src.agents.langgraph_agent import AgentState
        state: AgentState = {
            "task": "test",
            "task_input": {},
            "messages": [],
            "tool_calls": [],
            "result": None,
            "complete": False,
            "iterations": 0,
        }
        assert state["complete"] is False
        assert state["iterations"] == 0

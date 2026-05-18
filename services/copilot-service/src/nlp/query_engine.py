"""
CognitiveMDM Copilot Query Engine.
Translates natural language questions into graph queries and semantic searches,
then synthesises answers using Claude.
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator

import anthropic
import httpx
import structlog

logger = structlog.get_logger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
GRAPH_SERVICE_URL = os.environ.get("GRAPH_SERVICE_URL", "http://graph-service:8004")
ENTITY_RESOLUTION_URL = os.environ.get("ENTITY_RESOLUTION_URL", "http://entity-resolution:8002")
GOVERNANCE_URL = os.environ.get("GOVERNANCE_SERVICE_URL", "http://governance-service:8005")

SYSTEM_PROMPT = """You are CognitiveMDM Copilot, an AI assistant for enterprise master data management.

You have access to tools to query entity data, the knowledge graph, trust scores, and governance information.

Be concise and factual. When you retrieve data, present it clearly.
If you cannot find relevant data, say so. Do not fabricate entity IDs or records."""

COPILOT_TOOLS = [
    {
        "name": "search_entities",
        "description": "Search for entities by name, type, or keywords",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "entity_type": {"type": "string", "enum": ["customer", "product", "supplier", "employee", "asset"]},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_low_trust_entities",
        "description": "Find entities with trust scores below a threshold",
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold": {"type": "number"},
                "entity_type": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_governance_violations",
        "description": "Get governance policy violations, optionally filtered by severity",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "status": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_entity_graph",
        "description": "Get the relationship graph around an entity",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "find_entity_duplicates",
        "description": "Find potential duplicate records for an entity",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string"},
                "threshold": {"type": "number", "default": 0.75},
            },
            "required": ["entity_id"],
        },
    },
]


class CopilotQueryEngine:
    def __init__(self):
        self._client: anthropic.AsyncAnthropic | None = None
        self._http: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        if ANTHROPIC_API_KEY:
            self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            logger.info("copilot.initialized", model=LLM_MODEL)
        else:
            logger.warning("copilot.no_api_key")

    async def query(self, question: str, context: dict = {}) -> dict[str, Any]:
        if not self._client:
            return {"answer": "Copilot is not configured (missing ANTHROPIC_API_KEY)", "sources": []}

        messages = [{"role": "user", "content": question}]
        sources: list[dict] = []
        iterations = 0

        while iterations < 5:
            iterations += 1
            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=COPILOT_TOOLS,
                messages=messages,
            )

            assistant_content = []
            for block in response.content:
                if hasattr(block, "text"):
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                final_text = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    "No answer generated.",
                )
                return {"answer": final_text, "sources": sources, "iterations": iterations}

            # Execute tools
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await self._execute_tool(block.name, block.input)
                    sources.append({"tool": block.name, "query": block.input})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str)[:4000],
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

        return {"answer": "Max iterations reached.", "sources": sources, "iterations": iterations}

    async def stream_query(self, question: str) -> AsyncGenerator[str, None]:
        """Stream SSE events for the copilot response."""
        result = await self.query(question)
        answer = result.get("answer", "")
        # Stream word by word for UX
        for word in answer.split():
            yield f"data: {word} \n\n"
        yield "data: [DONE]\n\n"

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> Any:
        assert self._http
        try:
            if tool_name == "search_entities":
                resp = await self._http.post(
                    f"{ENTITY_RESOLUTION_URL}/entities/search",
                    json={"query": tool_input.get("query", ""), **tool_input},
                )
                return resp.json()

            elif tool_name == "get_low_trust_entities":
                # Query governance service for low-trust
                resp = await self._http.get(
                    f"{GOVERNANCE_URL}/governance/violations",
                    params={"limit": tool_input.get("limit", 20)},
                )
                return resp.json()

            elif tool_name == "get_governance_violations":
                params = {k: v for k, v in tool_input.items() if v is not None}
                resp = await self._http.get(
                    f"{GOVERNANCE_URL}/governance/violations", params=params
                )
                return resp.json()

            elif tool_name == "get_entity_graph":
                entity_id = tool_input["entity_id"]
                depth = tool_input.get("depth", 2)
                resp = await self._http.get(
                    f"{GRAPH_SERVICE_URL}/graph/neighborhood/{entity_id}",
                    params={"depth": depth},
                )
                return resp.json()

            elif tool_name == "find_entity_duplicates":
                entity_id = tool_input["entity_id"]
                threshold = tool_input.get("threshold", 0.75)
                resp = await self._http.get(
                    f"{ENTITY_RESOLUTION_URL}/entities/{entity_id}/duplicates",
                    params={"threshold": threshold},
                )
                return resp.json()

            return {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            return {"error": str(e)}

    async def get_suggestions(self, context: str = "") -> list[str]:
        return [
            "Find duplicate suppliers",
            "Which datasets have low trust scores?",
            "Show customer hierarchy for Acme Corp",
            "Which entities have PII governance violations?",
            "What products are related to oncology?",
            "Which systems violate data governance policies?",
            "Show me all unverified tier entities",
            "Find suppliers with missing tax IDs",
        ]

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

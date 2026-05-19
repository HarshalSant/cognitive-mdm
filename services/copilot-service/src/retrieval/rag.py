"""
GraphRAG Retrieval Engine.
Combines vector similarity search + knowledge graph traversal
to build rich context for LLM-powered copilot queries.

Architecture:
  1. Query â†' embed â†' Qdrant ANN search â†' candidate entities
  2. Candidates â†' Neo4j neighborhood â†' related entities / relationships
  3. Combined context â†' LLM prompt â†' structured answer
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

ENTITY_RESOLUTION_URL = os.environ.get("ENTITY_RESOLUTION_URL", "http://entity-resolution:8002")
GRAPH_SERVICE_URL = os.environ.get("GRAPH_SERVICE_URL", "http://graph-service:8004")
GOVERNANCE_URL = os.environ.get("GOVERNANCE_SERVICE_URL", "http://governance-service:8005")


@dataclass
class RetrievedContext:
    query: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    graph_nodes: list[dict[str, Any]] = field(default_factory=list)
    graph_edges: list[dict[str, Any]] = field(default_factory=list)
    violations: list[dict[str, Any]] = field(default_factory=list)
    total_retrieved: int = 0
    retrieval_methods: list[str] = field(default_factory=list)

    def to_prompt_context(self, max_entities: int = 8) -> str:
        """Build a compact LLM-ready context string."""
        lines = [f"Query context for: '{self.query}'"]

        if self.entities:
            lines.append(f"\nRelevant entities ({len(self.entities)} found):")
            for e in self.entities[:max_entities]:
                fields = e.get("fields", {})
                name = fields.get("name") or fields.get("full_name", e.get("id", "?")[:8])
                etype = e.get("entity_type", "?")
                lines.append(f"  - [{etype}] {name}: {_summarize_fields(fields)}")

        if self.graph_edges:
            lines.append(f"\nKnowledge graph relationships ({len(self.graph_edges)}):")
            for edge in self.graph_edges[:5]:
                lines.append(f"  - {edge.get('source', '?')} --[{edge.get('type', '?')}]--> {edge.get('target', '?')}")

        if self.violations:
            lines.append(f"\nGovernance context: {len(self.violations)} active violations")

        return "\n".join(lines)


def _summarize_fields(fields: dict) -> str:
    """Compact field summary -- show at most 3 key-value pairs."""
    skip = {"id", "created_at", "updated_at", "version"}
    items = [(k, v) for k, v in fields.items() if k not in skip and v][:3]
    return ", ".join(f"{k}={v}" for k, v in items)


class GraphRAGRetriever:
    """
    Retrieval engine for the copilot.
    Retrieves entities via semantic search and enriches with graph context.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient(timeout=30.0)

    async def retrieve(
        self,
        query: str,
        entity_type: str | None = None,
        top_k: int = 10,
        include_graph: bool = True,
        include_violations: bool = True,
    ) -> RetrievedContext:
        ctx = RetrievedContext(query=query)

        # 1. Semantic entity search
        entities = await self._search_entities(query, entity_type, top_k)
        ctx.entities = entities
        ctx.retrieval_methods.append("semantic_search")

        # 2. Graph neighborhood enrichment
        if include_graph and entities:
            for entity in entities[:3]:
                eid = entity.get("id", "")
                if eid:
                    nodes, edges = await self._get_graph_context(eid)
                    ctx.graph_nodes.extend(nodes)
                    ctx.graph_edges.extend(edges)
            ctx.retrieval_methods.append("graph_traversal")

        # 3. Governance context
        if include_violations:
            ctx.violations = await self._get_violations(limit=5)
            if ctx.violations:
                ctx.retrieval_methods.append("governance_context")

        ctx.total_retrieved = len(ctx.entities)
        return ctx

    async def retrieve_for_duplicates(
        self, entity_type: str | None = None
    ) -> RetrievedContext:
        """Specialized retrieval to find duplicate candidates."""
        ctx = RetrievedContext(query="duplicate detection")
        entities = await self._search_entities("", entity_type, top_k=50)
        ctx.entities = entities
        ctx.retrieval_methods.append("entity_scan")
        ctx.total_retrieved = len(entities)
        return ctx

    # â"€â"€ Private helpers â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

    async def _search_entities(
        self, query: str, entity_type: str | None, top_k: int
    ) -> list[dict]:
        try:
            payload: dict[str, Any] = {"query": query, "limit": top_k, "semantic": True}
            if entity_type:
                payload["entity_type"] = entity_type
            resp = await self._http.post(
                f"{ENTITY_RESOLUTION_URL}/api/v1/entities/search", json=payload
            )
            if resp.status_code == 200:
                return resp.json().get("entities", [])
        except Exception as e:
            logger.warning("retrieval.search_failed", error=str(e))
        return []

    async def _get_graph_context(
        self, entity_id: str, depth: int = 2
    ) -> tuple[list[dict], list[dict]]:
        try:
            resp = await self._http.get(
                f"{GRAPH_SERVICE_URL}/api/v1/graph/neighborhood/{entity_id}",
                params={"depth": depth},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("nodes", []), data.get("edges", [])
        except Exception as e:
            logger.warning("retrieval.graph_failed", error=str(e))
        return [], []

    async def _get_violations(self, limit: int = 10) -> list[dict]:
        try:
            resp = await self._http.get(
                f"{GOVERNANCE_URL}/api/v1/governance/violations",
                params={"status": "open", "limit": limit},
            )
            if resp.status_code == 200:
                return resp.json().get("violations", [])
        except Exception as e:
            logger.warning("retrieval.violations_failed", error=str(e))
        return []

    async def close(self) -> None:
        await self._http.aclose()

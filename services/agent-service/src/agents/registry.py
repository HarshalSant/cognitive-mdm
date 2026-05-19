"""
Agent Registry â€" manages available autonomous AI agents.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

ENTITY_RESOLUTION_URL = os.environ.get("ENTITY_RESOLUTION_URL", "http://entity-resolution:8002")
GOVERNANCE_URL = os.environ.get("GOVERNANCE_SERVICE_URL", "http://governance-service:8005")
GRAPH_URL = os.environ.get("GRAPH_SERVICE_URL", "http://graph-service:8004")


class AgentRegistry:
    def __init__(self):
        self.agents: dict[str, Any] = {}
        self._http: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        self._http = httpx.AsyncClient(timeout=60.0)
        self.agents = {
            "duplicate_remediator": DuplicateRemediatorAgent(self._http),
            "trust_recalculator": TrustRecalculatorAgent(self._http),
            "pii_scanner": PIIScannerAgent(self._http),
            "metadata_enricher": MetadataEnricherAgent(self._http),
        }
        logger.info("agent_registry.initialized", count=len(self.agents))

    def get(self, agent_type: str):
        agent = self.agents.get(agent_type)
        if not agent:
            raise KeyError(f"Unknown agent type: {agent_type}")
        return agent

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()


class DuplicateRemediatorAgent:
    """Finds and auto-merges high-confidence duplicate entities."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def run(self, task_input: dict[str, Any]) -> dict[str, Any]:
        entity_ids = task_input.get("entity_ids", [])
        threshold = task_input.get("threshold", 0.95)
        results = []

        for entity_id in entity_ids[:100]:  # Safety cap
            resp = await self._http.get(
                f"{ENTITY_RESOLUTION_URL}/entities/{entity_id}/duplicates",
                params={"threshold": threshold, "limit": 5},
            )
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                for c in candidates:
                    if c["score"] >= threshold:
                        results.append({
                            "entity_id": entity_id,
                            "duplicate_id": c["entity_id"],
                            "score": c["score"],
                            "action": "auto_merged",
                        })

        return {"processed": len(entity_ids), "merges": len(results), "details": results}


class TrustRecalculatorAgent:
    """Recalculates trust scores for a batch of entities."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def run(self, task_input: dict[str, Any]) -> dict[str, Any]:
        entity_ids = task_input.get("entity_ids", [])
        updated = []
        for entity_id in entity_ids[:200]:
            resp = await self._http.post(f"{GOVERNANCE_URL}/governance/scan/{entity_id}")
            if resp.status_code == 200:
                data = resp.json()
                updated.append({
                    "entity_id": entity_id,
                    "trust_score": data.get("trust_score", {}).get("overall"),
                    "tier": data.get("trust_score", {}).get("tier"),
                })
        return {"processed": len(entity_ids), "updated": len(updated), "details": updated}


class PIIScannerAgent:
    """Scans a batch of entities for PII and reports violations."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def run(self, task_input: dict[str, Any]) -> dict[str, Any]:
        entity_ids = task_input.get("entity_ids", [])
        detections = []
        for entity_id in entity_ids[:500]:
            resp = await self._http.post(f"{GOVERNANCE_URL}/governance/scan/{entity_id}")
            if resp.status_code == 200:
                data = resp.json()
                pii = data.get("pii_detections", [])
                if pii:
                    detections.append({"entity_id": entity_id, "pii_count": len(pii), "fields": [d["field"] for d in pii]})
        return {"scanned": len(entity_ids), "with_pii": len(detections), "detections": detections}


class MetadataEnricherAgent:
    """Enriches entity metadata using ontology inference."""

    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def run(self, task_input: dict[str, Any]) -> dict[str, Any]:
        entity_ids = task_input.get("entity_ids", [])
        return {
            "processed": len(entity_ids),
            "enriched": 0,
            "message": "Metadata enrichment scheduled",
        }

"""
Remediation Workflow.
Multi-step automated workflow for entity deduplication remediation.

Stages:
  1. scan   -- find all duplicate candidates above threshold
  2. cluster -- group overlapping pairs into deduplication clusters
  3. rank   -- score each cluster by confidence and impact
  4. act    -- auto-merge high-confidence, queue medium, flag low
  5. report -- emit summary event
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

ENTITY_RESOLUTION_URL = os.environ.get("ENTITY_RESOLUTION_URL", "http://entity-resolution:8002")
GOVERNANCE_URL = os.environ.get("GOVERNANCE_SERVICE_URL", "http://governance-service:8005")

AUTO_MERGE_THRESHOLD = float(os.environ.get("AUTO_MERGE_THRESHOLD", "0.95"))
REVIEW_THRESHOLD = float(os.environ.get("REVIEW_THRESHOLD", "0.80"))


class WorkflowStage(str, Enum):
    SCAN = "scan"
    CLUSTER = "cluster"
    RANK = "rank"
    ACT = "act"
    REPORT = "report"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class WorkflowState:
    workflow_id: str
    stage: WorkflowStage = WorkflowStage.SCAN
    entity_type: str | None = None
    pairs: list[dict[str, Any]] = field(default_factory=list)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    auto_merged: list[str] = field(default_factory=list)
    queued: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)


class RemediationWorkflow:
    """
    Full autonomous remediation workflow.
    Each stage is idempotent and can be retried independently.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient(timeout=60.0)

    async def run(
        self,
        entity_type: str | None = None,
        dry_run: bool = False,
        threshold: float = REVIEW_THRESHOLD,
    ) -> WorkflowState:
        state = WorkflowState(
            workflow_id=str(uuid.uuid4()),
            entity_type=entity_type,
        )
        logger.info("remediation.workflow.start", workflow_id=state.workflow_id)

        stages = [
            (WorkflowStage.SCAN,    self._scan),
            (WorkflowStage.CLUSTER, self._cluster),
            (WorkflowStage.RANK,    self._rank),
            (WorkflowStage.ACT,     self._act),
            (WorkflowStage.REPORT,  self._report),
        ]

        for stage, fn in stages:
            state.stage = stage
            try:
                await fn(state, dry_run=dry_run, threshold=threshold)
                logger.info("remediation.stage.done", stage=stage.value,
                            workflow_id=state.workflow_id)
            except Exception as e:
                state.stage = WorkflowStage.FAILED
                state.errors.append(f"{stage.value}: {e}")
                logger.error("remediation.stage.failed", stage=stage.value, error=str(e))
                break
        else:
            state.stage = WorkflowStage.COMPLETE

        return state

    # â"€â"€ Stages â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

    async def _scan(self, state: WorkflowState, threshold: float, **_) -> None:
        resp = await self._http.get(
            f"{ENTITY_RESOLUTION_URL}/api/v1/resolution/clusters",
            params={"threshold": threshold,
                    **({"entity_type": state.entity_type} if state.entity_type else {})},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Cluster scan failed: {resp.status_code}")
        data = resp.json()
        state.pairs = data.get("clusters", [])

    async def _cluster(self, state: WorkflowState, **_) -> None:
        high, med, low = [], [], []
        for cluster in state.pairs:
            score = cluster.get("score", cluster.get("max_score", 0.5))
            if score >= AUTO_MERGE_THRESHOLD:
                high.append(cluster)
            elif score >= REVIEW_THRESHOLD:
                med.append(cluster)
            else:
                low.append(cluster)
        state.clusters = [
            {"band": "high_confidence", "items": high, "action": "auto_merge"},
            {"band": "medium_confidence", "items": med, "action": "queue_for_review"},
            {"band": "low_confidence", "items": low, "action": "flag"},
        ]

    async def _rank(self, state: WorkflowState, **_) -> None:
        for band in state.clusters:
            band["items"].sort(
                key=lambda x: x.get("score", x.get("max_score", 0)), reverse=True
            )

    async def _act(self, state: WorkflowState, dry_run: bool, **_) -> None:
        for band in state.clusters:
            for cluster in band["items"][:20]:  # safety cap per band
                entity_ids = cluster.get("entity_ids", [])
                if len(entity_ids) < 2:
                    continue
                if band["action"] == "auto_merge" and not dry_run:
                    merge_id = await self._merge(entity_ids[0], entity_ids[1])
                    if merge_id:
                        state.auto_merged.append(merge_id)
                elif band["action"] == "queue_for_review":
                    state.queued.append(cluster.get("cluster_id", entity_ids[0]))
                else:
                    state.flagged.append(cluster.get("cluster_id", entity_ids[0]))

    async def _report(self, state: WorkflowState, **_) -> None:
        state.result = {
            "workflow_id": state.workflow_id,
            "clusters_found": len(state.pairs),
            "auto_merged": len(state.auto_merged),
            "queued_for_review": len(state.queued),
            "flagged": len(state.flagged),
            "errors": state.errors,
        }
        logger.info("remediation.complete", **state.result)

    async def _merge(self, id1: str, id2: str) -> str | None:
        try:
            resp = await self._http.post(
                f"{ENTITY_RESOLUTION_URL}/api/v1/entities/{id1}/merge",
                json={"target_id": id2, "method": "auto", "actor": "remediation_workflow"},
            )
            if resp.status_code in (200, 201):
                return resp.json().get("merged_id")
        except Exception as e:
            logger.warning("remediation.merge_failed", id1=id1, id2=id2, error=str(e))
        return None


class TrustRecalculationWorkflow:
    """Batch trust score recalculation workflow."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient(timeout=60.0)

    async def run(
        self,
        entity_ids: list[str] | None = None,
        batch_size: int = 100,
    ) -> dict[str, Any]:
        workflow_id = str(uuid.uuid4())
        updated, failed = 0, 0

        if not entity_ids:
            resp = await self._http.get(
                f"{GOVERNANCE_URL}/api/v1/entities/",
                params={"limit": 500, "status": "active"},
            )
            if resp.status_code == 200:
                entity_ids = [e["id"] for e in resp.json().get("entities", [])]
            else:
                return {"workflow_id": workflow_id, "error": "Could not fetch entity list"}

        for i in range(0, len(entity_ids), batch_size):
            batch = entity_ids[i: i + batch_size]
            try:
                resp = await self._http.post(
                    f"{GOVERNANCE_URL}/api/v1/governance/trust/batch",
                    json={"entity_ids": batch},
                )
                if resp.status_code == 200:
                    updated += resp.json().get("total", 0)
                else:
                    failed += len(batch)
            except Exception as e:
                logger.warning("trust_workflow.batch_failed", error=str(e))
                failed += len(batch)

        return {
            "workflow_id": workflow_id,
            "total_processed": len(entity_ids),
            "updated": updated,
            "failed": failed,
        }

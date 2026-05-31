"""
Pipeline Orchestrator -- the AI brain that routes events through
all intelligence stages and coordinates responses.

Stages (in order):
  1. Secret scan       -- block immediately on leaked credentials
  2. Vulnerability scan -- SAST + CVE findings with severity ranking
  3. Config audit      -- Dockerfile / CI YAML / Helm misconfigurations
  4. Dependency scan   -- third-party package CVEs
  5. Risk scoring      -- pre-deploy risk score + deployment decision
  6. Auto-fix          -- LLM-generated patches for fixable issues
  7. Pipeline optimize -- suggest/apply pipeline YAML improvements
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class PipelineStage(str, Enum):
    PENDING = "pending"
    SECRET_SCAN = "secret_scan"
    VULN_SCAN = "vuln_scan"
    CONFIG_AUDIT = "config_audit"
    DEP_SCAN = "dep_scan"
    RISK_SCORE = "risk_score"
    AUTO_FIX = "auto_fix"
    OPTIMIZE = "optimize"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    FAILED = "failed"


class DeployDecision(str, Enum):
    APPROVE = "approve"
    CANARY = "canary"
    HOLD = "hold"
    BLOCK = "block"


@dataclass
class StageResult:
    stage: PipelineStage
    passed: bool
    duration_ms: float
    findings: list[dict[str, Any]] = field(default_factory=list)
    fixes_applied: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 2),
            "finding_count": len(self.findings),
            "findings": self.findings[:10],
            "fixes_applied": self.fixes_applied,
            "metadata": self.metadata,
        }


@dataclass
class PipelineRun:
    run_id: str
    event_id: str
    repository: str
    branch: str
    commit_sha: str
    triggered_by: str
    started_at: datetime
    current_stage: PipelineStage = PipelineStage.PENDING
    stage_results: list[StageResult] = field(default_factory=list)
    deploy_decision: DeployDecision | None = None
    risk_score: float = 0.0
    finished_at: datetime | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "event_id": self.event_id,
            "repository": self.repository,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "triggered_by": self.triggered_by,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "current_stage": self.current_stage.value,
            "deploy_decision": self.deploy_decision.value if self.deploy_decision else None,
            "risk_score": round(self.risk_score, 2),
            "stages": [r.to_dict() for r in self.stage_results],
            "summary": self.summary,
            "duration_seconds": round(
                (self.finished_at - self.started_at).total_seconds(), 2
            ) if self.finished_at else None,
        }

    @property
    def total_findings(self) -> int:
        return sum(len(r.findings) for r in self.stage_results)

    @property
    def critical_findings(self) -> list[dict[str, Any]]:
        return [
            f for r in self.stage_results for f in r.findings
            if f.get("severity") in ("CRITICAL", "HIGH")
        ]

    @property
    def has_blocking_findings(self) -> bool:
        return any(f.get("blocking", False) for r in self.stage_results for f in r.findings)


class PipelineOrchestrator:
    """
    Coordinates all pipeline intelligence stages for a given PipelineRun.
    Scanners, risk scorer, and auto-fixer are injected as dependencies.
    """

    def __init__(
        self,
        vuln_scanner=None,
        secret_scanner=None,
        config_auditor=None,
        dep_scanner=None,
        risk_scorer=None,
        bug_fixer=None,
        optimizer=None,
    ) -> None:
        self._vuln = vuln_scanner
        self._secrets = secret_scanner
        self._config = config_auditor
        self._deps = dep_scanner
        self._risk = risk_scorer
        self._fixer = bug_fixer
        self._optimizer = optimizer
        self._runs: dict[str, PipelineRun] = {}

    def create_run(
        self,
        event_id: str,
        repository: str,
        branch: str,
        commit_sha: str,
        triggered_by: str = "system",
    ) -> PipelineRun:
        run = PipelineRun(
            run_id=str(uuid.uuid4())[:8],
            event_id=event_id,
            repository=repository,
            branch=branch,
            commit_sha=commit_sha,
            triggered_by=triggered_by,
            started_at=datetime.now(timezone.utc),
        )
        self._runs[run.run_id] = run
        logger.info("pipeline.run_created", run_id=run.run_id, repo=repository, branch=branch)
        return run

    async def execute(
        self,
        run: PipelineRun,
        code_content: str = "",
        config_content: str = "",
        dependencies: list[dict] | None = None,
        pipeline_yaml: str = "",
        build_history: list[dict] | None = None,
    ) -> PipelineRun:
        import time

        stages = [
            (PipelineStage.SECRET_SCAN, self._run_secret_scan, {"code": code_content}),
            (PipelineStage.VULN_SCAN, self._run_vuln_scan, {"code": code_content}),
            (PipelineStage.CONFIG_AUDIT, self._run_config_audit, {"content": config_content}),
            (PipelineStage.DEP_SCAN, self._run_dep_scan, {"deps": dependencies or []}),
            (PipelineStage.RISK_SCORE, self._run_risk_score, {"run": run}),
            (PipelineStage.AUTO_FIX, self._run_autofix, {"run": run, "code": code_content}),
            (PipelineStage.OPTIMIZE, self._run_optimize, {"yaml": pipeline_yaml, "history": build_history or []}),
        ]

        for stage, fn, kwargs in stages:
            run.current_stage = stage
            t0 = time.monotonic()
            try:
                result = await fn(**kwargs)
                result.duration_ms = (time.monotonic() - t0) * 1000
                run.stage_results.append(result)

                if not result.passed and stage == PipelineStage.SECRET_SCAN:
                    run.current_stage = PipelineStage.BLOCKED
                    run.deploy_decision = DeployDecision.BLOCK
                    run.finished_at = datetime.now(timezone.utc)
                    _finalize_summary(run)
                    logger.warning("pipeline.blocked_secret", run_id=run.run_id)
                    return run

            except Exception as e:
                logger.error("pipeline.stage_error", stage=stage.value, error=str(e))
                run.stage_results.append(StageResult(
                    stage=stage, passed=False, duration_ms=(time.monotonic() - t0) * 1000,
                    metadata={"error": str(e)},
                ))

        run.current_stage = PipelineStage.COMPLETE
        run.finished_at = datetime.now(timezone.utc)
        _finalize_summary(run)
        logger.info(
            "pipeline.run_complete",
            run_id=run.run_id,
            risk=run.risk_score,
            decision=run.deploy_decision.value if run.deploy_decision else "none",
            findings=run.total_findings,
        )
        return run

    # ---- Stage runners ------------------------------------------------------

    async def _run_secret_scan(self, code: str) -> StageResult:
        if self._secrets:
            findings = self._secrets.scan(code)
        else:
            findings = []
        has_critical = any(f.get("severity") == "CRITICAL" for f in findings)
        return StageResult(
            stage=PipelineStage.SECRET_SCAN,
            passed=not has_critical,
            duration_ms=0,
            findings=findings,
        )

    async def _run_vuln_scan(self, code: str) -> StageResult:
        if self._vuln:
            findings = self._vuln.scan(code)
        else:
            findings = []
        critical = [f for f in findings if f.get("severity") in ("CRITICAL", "HIGH")]
        return StageResult(
            stage=PipelineStage.VULN_SCAN,
            passed=len(critical) == 0,
            duration_ms=0,
            findings=findings,
        )

    async def _run_config_audit(self, content: str) -> StageResult:
        if self._config:
            findings = self._config.audit(content)
        else:
            findings = []
        blockers = [f for f in findings if f.get("blocking", False)]
        return StageResult(
            stage=PipelineStage.CONFIG_AUDIT,
            passed=len(blockers) == 0,
            duration_ms=0,
            findings=findings,
        )

    async def _run_dep_scan(self, deps: list[dict]) -> StageResult:
        if self._deps:
            findings = self._deps.scan(deps)
        else:
            findings = []
        critical = [f for f in findings if f.get("severity") in ("CRITICAL", "HIGH")]
        return StageResult(
            stage=PipelineStage.DEP_SCAN,
            passed=len(critical) == 0,
            duration_ms=0,
            findings=findings,
        )

    async def _run_risk_score(self, run: PipelineRun) -> StageResult:
        if self._risk:
            score_result = self._risk.score(
                branch=run.branch,
                findings=[f for r in run.stage_results for f in r.findings],
                commit_sha=run.commit_sha,
            )
            run.risk_score = score_result["score"]
            run.deploy_decision = _decision_from_score(score_result["score"])
            return StageResult(
                stage=PipelineStage.RISK_SCORE,
                passed=True,
                duration_ms=0,
                metadata=score_result,
            )
        run.risk_score = 20.0
        run.deploy_decision = DeployDecision.APPROVE
        return StageResult(stage=PipelineStage.RISK_SCORE, passed=True, duration_ms=0)

    async def _run_autofix(self, run: PipelineRun, code: str) -> StageResult:
        if not self._fixer:
            return StageResult(stage=PipelineStage.AUTO_FIX, passed=True, duration_ms=0)
        fixable = [
            f for r in run.stage_results for f in r.findings
            if f.get("fixable", False)
        ]
        fixes = []
        for finding in fixable[:5]:
            fix = await self._fixer.fix(finding, code)
            if fix:
                fixes.append(fix)
        return StageResult(
            stage=PipelineStage.AUTO_FIX,
            passed=True,
            duration_ms=0,
            fixes_applied=fixes,
            metadata={"fixes_generated": len(fixes)},
        )

    async def _run_optimize(self, yaml: str, history: list[dict]) -> StageResult:
        if not self._optimizer or not yaml:
            return StageResult(stage=PipelineStage.OPTIMIZE, passed=True, duration_ms=0)
        suggestions = self._optimizer.analyze(yaml, history)
        return StageResult(
            stage=PipelineStage.OPTIMIZE,
            passed=True,
            duration_ms=0,
            metadata={"suggestions": suggestions},
        )

    # ---- Query --------------------------------------------------------------

    def get_run(self, run_id: str) -> PipelineRun | None:
        return self._runs.get(run_id)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        runs = sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)
        return [r.to_dict() for r in runs[:limit]]

    def get_stats(self) -> dict[str, Any]:
        runs = list(self._runs.values())
        decisions: dict[str, int] = {}
        for r in runs:
            d = r.deploy_decision.value if r.deploy_decision else "pending"
            decisions[d] = decisions.get(d, 0) + 1
        total_findings = sum(r.total_findings for r in runs)
        avg_risk = round(sum(r.risk_score for r in runs) / len(runs), 2) if runs else 0
        return {
            "total_runs": len(runs),
            "decisions": decisions,
            "total_findings": total_findings,
            "average_risk_score": avg_risk,
        }


# ---- Helpers ----------------------------------------------------------------

def _decision_from_score(score: float) -> DeployDecision:
    if score <= 30:
        return DeployDecision.APPROVE
    if score <= 65:
        return DeployDecision.CANARY
    if score <= 85:
        return DeployDecision.HOLD
    return DeployDecision.BLOCK


def _finalize_summary(run: PipelineRun) -> None:
    stages_passed = sum(1 for r in run.stage_results if r.passed)
    run.summary = {
        "total_stages": len(run.stage_results),
        "stages_passed": stages_passed,
        "total_findings": run.total_findings,
        "critical_findings": len(run.critical_findings),
        "deploy_decision": run.deploy_decision.value if run.deploy_decision else None,
        "risk_score": round(run.risk_score, 2),
        "blocked": run.current_stage == PipelineStage.BLOCKED,
    }

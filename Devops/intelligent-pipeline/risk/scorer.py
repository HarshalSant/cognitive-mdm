"""
Pre-Deploy Risk Scorer -- multi-dimensional risk engine that produces a
0-100 risk score and a deployment recommendation before every release.

Dimensions:
  branch_risk       (0.20) -- production vs feature branch
  finding_risk      (0.30) -- severity/count of scan findings
  change_risk       (0.20) -- infra, dependency, or security file changes
  history_risk      (0.15) -- recent incident/failure rate on this repo
  blast_radius      (0.15) -- estimated services/users impacted
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class RiskDimension:
    name: str
    score: float
    weight: float
    rationale: str

    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class RiskResult:
    score: float
    level: str
    decision: str
    canary_percentage: int | None
    dimensions: list[RiskDimension]
    rationale: str
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "level": self.level,
            "decision": self.decision,
            "canary_percentage": self.canary_percentage,
            "rationale": self.rationale,
            "recommendations": self.recommendations,
            "dimensions": [
                {
                    "name": d.name,
                    "score": round(d.score, 2),
                    "weight": d.weight,
                    "weighted_score": round(d.weighted(), 2),
                    "rationale": d.rationale,
                }
                for d in self.dimensions
            ],
        }


PROD_BRANCHES = {"main", "master", "production", "release", "prod"}
HIGH_RISK_PATHS = {
    "auth", "security", "payment", "billing", "user", "database",
    "migration", "infra", "terraform", "k8s", "kubernetes", "helm",
}


class RiskScorer:
    """
    Deterministic, dependency-free risk scorer.
    All logic is reproducible and auditable -- no ML black boxes.
    """

    def score(
        self,
        branch: str,
        findings: list[dict[str, Any]],
        commit_sha: str = "",
        files_changed: list[str] | None = None,
        build_history: list[dict[str, Any]] | None = None,
        service_count: int = 1,
        user_count: int = 100,
    ) -> dict[str, Any]:
        dims = [
            self._branch_dimension(branch),
            self._finding_dimension(findings),
            self._change_dimension(files_changed or []),
            self._history_dimension(build_history or []),
            self._blast_dimension(service_count, user_count),
        ]

        raw = sum(d.weighted() for d in dims)
        score = min(100.0, max(0.0, raw))

        level, decision, canary, rationale = _interpret(score, dims)
        recommendations = _build_recommendations(score, dims, findings)

        result = RiskResult(
            score=score,
            level=level,
            decision=decision,
            canary_percentage=canary,
            dimensions=dims,
            rationale=rationale,
            recommendations=recommendations,
        )
        return result.to_dict()

    def _branch_dimension(self, branch: str) -> RiskDimension:
        is_prod = branch.lower() in PROD_BRANCHES or branch.lower().startswith("release/")
        score = 80.0 if is_prod else 20.0
        return RiskDimension(
            name="branch_risk",
            score=score,
            weight=0.20,
            rationale=f"Branch '{branch}' is {'production' if is_prod else 'non-production'}",
        )

    def _finding_dimension(self, findings: list[dict]) -> RiskDimension:
        if not findings:
            return RiskDimension("finding_risk", 0.0, 0.30, "No findings")

        sev_scores = {"CRITICAL": 100, "HIGH": 75, "MEDIUM": 40, "LOW": 15, "INFO": 5}
        weighted_sum = sum(sev_scores.get(f.get("severity", "LOW"), 15) for f in findings)
        avg = weighted_sum / len(findings)
        volume_penalty = min(30, len(findings) * 3)
        score = min(100.0, avg + volume_penalty)

        critical = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high = sum(1 for f in findings if f.get("severity") == "HIGH")
        return RiskDimension(
            name="finding_risk",
            score=score,
            weight=0.30,
            rationale=f"{len(findings)} findings: {critical} critical, {high} high",
        )

    def _change_dimension(self, files: list[str]) -> RiskDimension:
        if not files:
            return RiskDimension("change_risk", 10.0, 0.20, "No file change info")

        risk = 10.0
        reasons = []

        high_risk = [f for f in files if any(hr in f.lower() for hr in HIGH_RISK_PATHS)]
        if high_risk:
            risk += 40
            reasons.append(f"{len(high_risk)} high-risk path(s) modified")

        infra = [f for f in files if any(f.endswith(e) for e in [".tf", ".yaml", ".yml", "Dockerfile"])]
        if infra:
            risk += 25
            reasons.append(f"{len(infra)} infra file(s) changed")

        deps = [f for f in files if any(d in f for d in ["requirements", "package.json", "pom.xml", "go.mod"])]
        if deps:
            risk += 20
            reasons.append("dependency manifest changed")

        volume_penalty = min(20, len(files) * 0.5)
        risk = min(100.0, risk + volume_penalty)

        return RiskDimension(
            name="change_risk",
            score=risk,
            weight=0.20,
            rationale="; ".join(reasons) if reasons else f"{len(files)} files changed",
        )

    def _history_dimension(self, history: list[dict]) -> RiskDimension:
        if not history:
            return RiskDimension("history_risk", 20.0, 0.15, "No history available")

        recent = history[-10:]
        failures = sum(1 for r in recent if r.get("result") == "failed")
        incidents = sum(1 for r in recent if r.get("had_incident", False))
        rollbacks = sum(1 for r in recent if r.get("was_rollback", False))

        failure_rate = failures / len(recent)
        score = min(100.0, failure_rate * 80 + incidents * 10 + rollbacks * 15)

        return RiskDimension(
            name="history_risk",
            score=score,
            weight=0.15,
            rationale=(
                f"Last {len(recent)} runs: {failures} failed, "
                f"{incidents} incidents, {rollbacks} rollbacks"
            ),
        )

    def _blast_dimension(self, service_count: int, user_count: int) -> RiskDimension:
        service_risk = min(50, service_count * 10)
        user_risk = min(50, math.log10(max(1, user_count)) * 15)
        score = service_risk + user_risk
        return RiskDimension(
            name="blast_radius",
            score=min(100.0, score),
            weight=0.15,
            rationale=f"{service_count} dependent service(s), ~{user_count} affected users",
        )


def _interpret(
    score: float, dims: list[RiskDimension]
) -> tuple[str, str, int | None, str]:
    if score <= 25:
        return "LOW", "approve", None, "Low risk -- safe to deploy directly"
    if score <= 50:
        return "MEDIUM", "approve", None, "Moderate risk -- proceed with standard monitoring"
    if score <= 70:
        canary = 10 if score > 60 else 25
        return "HIGH", "canary", canary, f"High risk -- canary deploy at {canary}% recommended"
    if score <= 85:
        return "VERY_HIGH", "hold", None, "Very high risk -- hold for off-peak window and senior review"
    return "CRITICAL", "block", None, "Critical risk -- block deployment until findings resolved"


def _build_recommendations(
    score: float,
    dims: list[RiskDimension],
    findings: list[dict],
) -> list[str]:
    recs = []
    dim_map = {d.name: d for d in dims}

    if dim_map.get("finding_risk", RiskDimension("", 0, 0, "")).score > 50:
        critical = [f for f in findings if f.get("severity") == "CRITICAL"]
        if critical:
            recs.append(f"Resolve {len(critical)} CRITICAL finding(s) before deploying")

    if dim_map.get("history_risk", RiskDimension("", 0, 0, "")).score > 40:
        recs.append("Recent failure history detected -- verify fix in staging first")

    if dim_map.get("change_risk", RiskDimension("", 0, 0, "")).score > 50:
        recs.append("Infrastructure or auth files changed -- ensure rollback plan is ready")

    if score > 65:
        recs.append("Enable enhanced monitoring (error rate, latency, saturation) post-deploy")

    if score > 50 and not any("canary" in r for r in recs):
        recs.append("Consider canary or blue-green deployment strategy")

    if not recs:
        recs.append("Proceed with standard deployment checklist")

    return recs

"""
IntelliPipeline -- AI-Native CI/CD Autopilot
All-in-one development server. No Docker, no external services required.

Run:  python dev_server.py
Docs: http://localhost:9001/docs
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---- local imports ----------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from core.config import PORT, SERVICE_NAME, SERVICE_VERSION
from core.event_bus import EventBus, EventType, EventSource, PipelineEvent
from core.orchestrator import PipelineOrchestrator, PipelineStage, DeployDecision
from scanners.vulnerability import VulnerabilityScanner
from scanners.secrets import SecretScanner
from scanners.config_auditor import ConfigAuditor
from scanners.dependency import DependencyScanner
from autofix.bug_fixer import BugFixer
from autofix.optimizer import PipelineOptimizer
from autofix.pr_generator import PRGenerator
from risk.scorer import RiskScorer
from gitops.drift_detector import DriftDetector
from k8s.health_monitor import KubernetesHealthMonitor
from k8s.predictor import PredictiveScaler
from integrations.github import GitHubClient

logger = structlog.get_logger(__name__)

# ---- Application setup ------------------------------------------------------

app = FastAPI(
    title="IntelliPipeline",
    description="AI-Native CI/CD Autopilot -- security scanning, auto-fix, risk scoring, GitOps drift, K8s intelligence",
    version=SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Service singletons -----------------------------------------------------

_vuln_scanner = VulnerabilityScanner()
_secret_scanner = SecretScanner()
_config_auditor = ConfigAuditor()
_dep_scanner = DependencyScanner()
_bug_fixer = BugFixer()
_optimizer = PipelineOptimizer()
_pr_generator = PRGenerator()
_risk_scorer = RiskScorer()
_drift_detector = DriftDetector()
_health_monitor = KubernetesHealthMonitor()
_predictor = PredictiveScaler()
_event_bus = EventBus()
_github_client = GitHubClient()
_orchestrator = PipelineOrchestrator(
    vuln_scanner=_vuln_scanner,
    secret_scanner=_secret_scanner,
    config_auditor=_config_auditor,
    dep_scanner=_dep_scanner,
    risk_scorer=_risk_scorer,
    bug_fixer=_bug_fixer,
    optimizer=_optimizer,
)

# ---- In-memory state --------------------------------------------------------

_scan_history: list[dict[str, Any]] = []
_run_history: list[dict[str, Any]] = []
_audit_log: list[dict[str, Any]] = []


def _log_audit(action: str, details: dict[str, Any]) -> None:
    _audit_log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        **details,
    })
    if len(_audit_log) > 500:
        _audit_log.pop(0)


# ============================================================================
# Request / Response models
# ============================================================================

class ScanRequest(BaseModel):
    code: str = Field("", description="Source code to scan")
    language: str = Field("python", description="Programming language")
    file_path: str = Field("<content>", description="File path (for reporting)")


class ConfigAuditRequest(BaseModel):
    content: str = Field(..., description="Config file content (Dockerfile, CI YAML, Helm values)")
    config_type: str | None = Field(None, description="Force config type: dockerfile | github_actions | helm_values")


class DependencyRequest(BaseModel):
    dependencies: list[dict[str, Any]] = Field(..., description='[{"name":"django","version":"3.0","ecosystem":"python"}]')


class BuildFixRequest(BaseModel):
    error_log: str = Field(..., description="CI/CD build failure log")
    source_files: dict[str, str] = Field(default_factory=dict, description="Relevant source files {path: content}")


class PipelineRunRequest(BaseModel):
    repository: str = Field(..., description="owner/repo")
    branch: str = Field("main", description="Branch name")
    commit_sha: str = Field("HEAD", description="Commit SHA")
    code: str = Field("", description="Source code to scan")
    config_content: str = Field("", description="Dockerfile/CI YAML to audit")
    pipeline_yaml: str = Field("", description="CI pipeline YAML for optimization")
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    triggered_by: str = Field("user")


class OptimizeRequest(BaseModel):
    pipeline_yaml: str = Field(..., description="CI pipeline YAML")
    build_history: list[dict[str, Any]] = Field(default_factory=list)
    runs_per_day: int = Field(20, ge=1, le=1000)


class RiskScoreRequest(BaseModel):
    branch: str = Field("main")
    files_changed: list[str] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    build_history: list[dict[str, Any]] = Field(default_factory=list)
    service_count: int = Field(1, ge=1)
    user_count: int = Field(100, ge=1)
    commit_sha: str = Field("")


class DriftRequest(BaseModel):
    argocd_apps: list[dict[str, Any]] = Field(default_factory=list)
    flux_kustomizations: list[dict[str, Any]] = Field(default_factory=list)
    desired_yaml: str = Field("")
    actual_yaml: str = Field("")


class K8sHealthRequest(BaseModel):
    pods: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)


class PredictScalingRequest(BaseModel):
    workload: str = Field(..., description="Deployment name")
    namespace: str = Field("default")
    current_replicas: int = Field(2, ge=1)
    metrics_history: list[dict[str, Any]] = Field(..., description='[{"cpu_utilization":0.6,"memory_utilization":0.5}]')
    lookahead_minutes: int = Field(30, ge=5, le=120)


class GitHubWebhookRequest(BaseModel):
    event_type: str = Field(..., description="github push | pull_request")
    payload: dict[str, Any] = Field(...)


# ============================================================================
# Routes
# ============================================================================

@app.get("/", tags=["Health"])
async def root():
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status": "operational",
        "endpoints": [
            "/api/v1/scan/code",
            "/api/v1/scan/secrets",
            "/api/v1/scan/config",
            "/api/v1/scan/dependencies",
            "/api/v1/pipeline/run",
            "/api/v1/autofix/build-failure",
            "/api/v1/optimize/pipeline",
            "/api/v1/risk/score",
            "/api/v1/gitops/drift",
            "/api/v1/k8s/health",
            "/api/v1/k8s/predict-scaling",
            "/api/v1/webhook/github",
            "/api/v1/analytics/summary",
            "/docs",
        ],
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


# ============================================================================
# SCAN endpoints
# ============================================================================

@app.post("/api/v1/scan/code", tags=["Scanning"])
async def scan_code(req: ScanRequest):
    """SAST vulnerability scan on source code."""
    findings = _vuln_scanner.scan(req.code, req.language)
    summary = _vuln_scanner.get_summary(findings)
    result = {
        "scan_id": str(uuid.uuid4())[:8],
        "language": req.language,
        "file_path": req.file_path,
        "findings": findings,
        "summary": summary,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
    _scan_history.append(result)
    _log_audit("code_scan", {"language": req.language, "finding_count": len(findings)})
    return result


@app.post("/api/v1/scan/secrets", tags=["Scanning"])
async def scan_secrets(req: ScanRequest):
    """Detect leaked credentials, API keys, and tokens in source code."""
    findings = _secret_scanner.scan(req.code, req.file_path)
    blocking = [f for f in findings if f.get("blocking")]
    result = {
        "scan_id": str(uuid.uuid4())[:8],
        "findings": findings,
        "blocking_count": len(blocking),
        "total_count": len(findings),
        "blocked": len(blocking) > 0,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
    _log_audit("secret_scan", {"finding_count": len(findings), "blocked": result["blocked"]})
    return result


@app.post("/api/v1/scan/config", tags=["Scanning"])
async def audit_config(req: ConfigAuditRequest):
    """Audit Dockerfile, CI YAML, or Helm values for misconfigurations."""
    result = _config_auditor.audit_with_fix(req.content, req.config_type)
    result["audit_id"] = str(uuid.uuid4())[:8]
    result["audited_at"] = datetime.now(timezone.utc).isoformat()
    _log_audit("config_audit", {
        "config_type": req.config_type,
        "finding_count": result["finding_count"],
        "fixes_applied": len(result.get("applied_fixes", [])),
    })
    return result


@app.post("/api/v1/scan/dependencies", tags=["Scanning"])
async def scan_dependencies(req: DependencyRequest):
    """Scan package dependencies for known CVEs."""
    findings = _dep_scanner.scan(req.dependencies)
    summary = _dep_scanner.get_summary(findings)
    result = {
        "scan_id": str(uuid.uuid4())[:8],
        "package_count": len(req.dependencies),
        "findings": findings,
        "summary": summary,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }
    _log_audit("dep_scan", {"packages": len(req.dependencies), "vulns": len(findings)})
    return result


@app.post("/api/v1/scan/requirements-txt", tags=["Scanning"])
async def scan_requirements_txt(request: Request):
    """Parse and scan a requirements.txt file for vulnerable packages."""
    body = await request.body()
    content = body.decode("utf-8")
    deps = _dep_scanner.parse_requirements_txt(content)
    findings = _dep_scanner.scan(deps)
    return {
        "packages_found": len(deps),
        "vulnerabilities": len(findings),
        "findings": findings,
        "summary": _dep_scanner.get_summary(findings),
    }


# ============================================================================
# Pipeline orchestration
# ============================================================================

@app.post("/api/v1/pipeline/run", tags=["Pipeline"])
async def run_pipeline(req: PipelineRunRequest):
    """
    Execute the full IntelliPipeline analysis on a code push/PR event.
    Runs all 7 stages: secret scan, SAST, config audit, dep scan, risk score, autofix, optimize.
    """
    event = _event_bus.from_manual(req.repository, req.branch, req.triggered_by)
    run = _orchestrator.create_run(
        event_id=event.event_id,
        repository=req.repository,
        branch=req.branch,
        commit_sha=req.commit_sha,
        triggered_by=req.triggered_by,
    )

    completed_run = await _orchestrator.execute(
        run,
        code_content=req.code,
        config_content=req.config_content,
        dependencies=req.dependencies,
        pipeline_yaml=req.pipeline_yaml,
    )

    result = completed_run.to_dict()
    _run_history.append(result)
    if len(_run_history) > 200:
        _run_history.pop(0)

    _log_audit("pipeline_run", {
        "run_id": run.run_id,
        "repository": req.repository,
        "branch": req.branch,
        "risk_score": completed_run.risk_score,
        "decision": completed_run.deploy_decision.value if completed_run.deploy_decision else None,
        "total_findings": completed_run.total_findings,
    })
    return result


@app.get("/api/v1/pipeline/runs", tags=["Pipeline"])
async def list_runs(limit: int = 20):
    """List recent pipeline runs."""
    return {"runs": _orchestrator.list_runs(limit), "total": len(_run_history)}


@app.get("/api/v1/pipeline/runs/{run_id}", tags=["Pipeline"])
async def get_run(run_id: str):
    """Get details of a specific pipeline run."""
    run = _orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run.to_dict()


# ============================================================================
# Auto-fix
# ============================================================================

@app.post("/api/v1/autofix/build-failure", tags=["AutoFix"])
async def fix_build_failure(req: BuildFixRequest):
    """
    Analyse a CI build failure log and generate targeted fix suggestions.
    Uses Claude API when available, falls back to pattern-based analysis.
    """
    result = await _bug_fixer.fix_build_failure(req.error_log, req.source_files)
    result["fix_id"] = str(uuid.uuid4())[:8]
    result["analysed_at"] = datetime.now(timezone.utc).isoformat()
    _log_audit("build_fix", {"error_type": result.get("error_type"), "confidence": result.get("confidence")})
    return result


# ============================================================================
# Pipeline optimization
# ============================================================================

@app.post("/api/v1/optimize/pipeline", tags=["Optimization"])
async def optimize_pipeline(req: OptimizeRequest):
    """
    Analyse a CI pipeline YAML and build history to identify optimisation opportunities.
    Returns suggestions with estimated time and cost savings.
    """
    suggestions = _optimizer.analyze(req.pipeline_yaml, req.build_history)
    savings = _optimizer.estimate_monthly_savings(suggestions, req.runs_per_day)
    pr_payload = _pr_generator.from_optimizer_suggestions(
        suggestions, savings, run_id=str(uuid.uuid4())[:8]
    )
    return {
        "optimization_id": str(uuid.uuid4())[:8],
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
        "estimated_savings": savings,
        "draft_pr": pr_payload.to_dict(),
        "analysed_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# Risk scoring
# ============================================================================

@app.post("/api/v1/risk/score", tags=["Risk"])
async def score_risk(req: RiskScoreRequest):
    """
    Calculate pre-deploy risk score (0-100) with deployment recommendation.
    Returns: APPROVE | CANARY | HOLD | BLOCK
    """
    result = _risk_scorer.score(
        branch=req.branch,
        findings=req.findings,
        commit_sha=req.commit_sha,
        files_changed=req.files_changed,
        build_history=req.build_history,
        service_count=req.service_count,
        user_count=req.user_count,
    )
    result["scored_at"] = datetime.now(timezone.utc).isoformat()
    _log_audit("risk_score", {
        "branch": req.branch,
        "score": result["score"],
        "decision": result["decision"],
    })
    return result


# ============================================================================
# GitOps drift
# ============================================================================

@app.post("/api/v1/gitops/drift", tags=["GitOps"])
async def detect_drift(req: DriftRequest):
    """
    Detect GitOps drift between desired (Git) and actual (cluster) state.
    Supports ArgoCD apps, Flux kustomizations, and raw YAML diff.
    """
    events: list[dict] = []

    if req.argocd_apps:
        events.extend(_drift_detector.analyze_argocd_apps(req.argocd_apps))

    if req.flux_kustomizations:
        events.extend(_drift_detector.analyze_flux_kustomizations(req.flux_kustomizations))

    if req.desired_yaml and req.actual_yaml:
        events.extend(_drift_detector.analyze_manifest_text(req.desired_yaml, req.actual_yaml))

    reconciliation_plan = _drift_detector.get_reconciliation_plan(events)

    result = {
        "drift_id": str(uuid.uuid4())[:8],
        "drift_events": events,
        "reconciliation_plan": reconciliation_plan,
        "has_critical_drift": any(e.get("severity") == "CRITICAL" for e in events),
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    _log_audit("drift_detection", {
        "event_count": len(events),
        "critical": reconciliation_plan.get("critical"),
    })
    return result


# ============================================================================
# Kubernetes intelligence
# ============================================================================

@app.post("/api/v1/k8s/health", tags=["Kubernetes"])
async def check_k8s_health(req: K8sHealthRequest):
    """
    Analyse Kubernetes pod status and resource metrics for health issues.
    Pass raw kubectl get pods -o json output.
    """
    pod_issues = _health_monitor.analyze_pods(req.pods)
    resource_issues = _health_monitor.analyze_resource_utilization(req.metrics)
    summary = _health_monitor.cluster_health_summary(pod_issues, resource_issues)
    summary["checked_at"] = datetime.now(timezone.utc).isoformat()
    summary["pod_count"] = len(req.pods)
    _log_audit("k8s_health_check", {
        "pod_count": len(req.pods),
        "issue_count": len(pod_issues) + len(resource_issues),
        "status": summary.get("overall_status"),
    })
    return summary


@app.post("/api/v1/k8s/predict-scaling", tags=["Kubernetes"])
async def predict_scaling(req: PredictScalingRequest):
    """
    Predict load spikes and recommend pre-emptive scaling actions.
    Uses exponential smoothing + time-of-day patterns.
    """
    recommendation = _predictor.predict_and_recommend(
        workload=req.workload,
        namespace=req.namespace,
        current_replicas=req.current_replicas,
        metrics_history=req.metrics_history,
        lookahead_minutes=req.lookahead_minutes,
    )
    right_size = _predictor.right_size_resources(req.metrics_history)
    return {
        "workload": req.workload,
        "current_replicas": req.current_replicas,
        "scaling_recommendation": recommendation.to_dict() if recommendation else None,
        "action_needed": recommendation is not None,
        "resource_right_sizing": right_size,
        "predicted_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# Webhook ingestion
# ============================================================================

@app.post("/api/v1/webhook/github", tags=["Webhooks"])
async def github_webhook(req: GitHubWebhookRequest):
    """Ingest a GitHub webhook event and trigger pipeline analysis."""
    if req.event_type == "push":
        event = _event_bus.from_github_push(req.payload)
    elif req.event_type == "pull_request":
        event = _event_bus.from_github_pr(req.payload)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported event_type: {req.event_type}")

    await _event_bus.emit(event)
    _log_audit("webhook_github", {
        "event_type": req.event_type,
        "repo": event.repository,
        "branch": event.branch,
        "event_id": event.event_id,
    })
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "repository": event.repository,
        "branch": event.branch,
        "received_at": event.timestamp.isoformat(),
        "status": "accepted",
    }


@app.get("/api/v1/webhook/events", tags=["Webhooks"])
async def list_webhook_events(limit: int = 50):
    """List recent webhook events received."""
    return {
        "events": _event_bus.get_recent(limit),
        "stats": _event_bus.get_stats(),
    }


# ============================================================================
# Analytics
# ============================================================================

@app.get("/api/v1/analytics/summary", tags=["Analytics"])
async def analytics_summary():
    """Global IntelliPipeline analytics -- runs, findings, risk distribution."""
    pipeline_stats = _orchestrator.get_stats()
    scan_counts = len(_scan_history)

    decision_dist: dict[str, int] = {}
    risk_scores = []
    for run in _run_history:
        d = run.get("deploy_decision", "unknown")
        decision_dist[d] = decision_dist.get(d, 0) + 1
        if run.get("risk_score") is not None:
            risk_scores.append(run["risk_score"])

    avg_risk = round(sum(risk_scores) / len(risk_scores), 2) if risk_scores else 0

    return {
        "pipeline": pipeline_stats,
        "total_scans": scan_counts,
        "decision_distribution": decision_dist,
        "average_risk_score": avg_risk,
        "event_stats": _event_bus.get_stats(),
        "audit_log_size": len(_audit_log),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/analytics/audit-log", tags=["Analytics"])
async def get_audit_log(limit: int = 100):
    """Get the recent audit log of all IntelliPipeline actions."""
    return {"entries": _audit_log[-limit:], "total": len(_audit_log)}


# ============================================================================
# Demo seed endpoint
# ============================================================================

@app.post("/api/v1/demo/seed", tags=["Demo"])
async def seed_demo():
    """
    Seed the system with realistic demo data to showcase all capabilities.
    Safe to call multiple times.
    """
    results: list[str] = []

    # 1. Scan vulnerable Python code
    vuln_code = '''
import sqlite3
import os
import yaml

def get_user(user_id):
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = " + user_id)  # SQL injection
    return cursor.fetchone()

def run_command(cmd):
    os.system("echo " + cmd)  # Command injection

config = yaml.load(open("config.yml"))  # Unsafe yaml.load

SECRET_KEY = "hardcoded-jwt-secret-key-123"  # Hardcoded secret

app.run(debug=True)  # Debug in production
'''
    vuln_findings = _vuln_scanner.scan(vuln_code, "python")
    results.append(f"SAST: found {len(vuln_findings)} vulnerabilities in demo code")

    # 2. Scan for secrets
    secret_code = '''
GITHUB_TOKEN = "ghp_abc123DEF456ghi789JKL012mno345pqr678"
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
DB_URL = "postgres://admin:password123@db.internal:5432/prod"
'''
    secret_findings = _secret_scanner.scan(secret_code, "config.py")
    results.append(f"Secrets: found {len(secret_findings)} secrets in demo code")

    # 3. Audit a bad Dockerfile
    bad_dockerfile = """FROM ubuntu:latest
USER root
ENV DB_PASSWORD=supersecret123
RUN apt-get install -y curl wget
COPY . .
RUN pip install -r requirements.txt
EXPOSE 22
CMD ["python", "app.py"]
"""
    config_findings = _config_auditor.audit(bad_dockerfile, "dockerfile")
    results.append(f"Config: found {len(config_findings)} Dockerfile issues")

    # 4. Scan vulnerable dependencies
    deps = [
        {"name": "django", "version": "3.2.0", "ecosystem": "python"},
        {"name": "pyyaml", "version": "5.4.0", "ecosystem": "python"},
        {"name": "log4j-core", "version": "2.14.0", "ecosystem": "java"},
        {"name": "lodash", "version": "4.17.15", "ecosystem": "nodejs"},
        {"name": "minimist", "version": "1.2.5", "ecosystem": "nodejs"},
    ]
    dep_findings = _dep_scanner.scan(deps)
    results.append(f"Dependencies: found {len(dep_findings)} CVEs in {len(deps)} packages")

    # 5. Score deployment risk
    all_findings = vuln_findings + config_findings + dep_findings
    risk = _risk_scorer.score(
        branch="main",
        findings=all_findings,
        files_changed=["auth/models.py", "requirements.txt", "Dockerfile", "k8s/deployment.yaml"],
        service_count=4,
        user_count=5000,
    )
    results.append(f"Risk score: {risk['score']:.0f}/100 -- decision: {risk['decision'].upper()}")

    # 6. Optimize a pipeline
    bad_pipeline = """
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@main
      - run: pip install -r requirements.txt
      - run: pytest tests/
      - run: docker build -t myapp .
      - run: docker push myapp
"""
    suggestions = _optimizer.analyze(bad_pipeline, [])
    savings = _optimizer.estimate_monthly_savings(suggestions)
    results.append(
        f"Optimizer: {len(suggestions)} suggestions -- "
        f"save ${savings['estimated_monthly_cost_saving_usd']:.0f}/month"
    )

    # 7. Detect simulated GitOps drift
    argocd_apps = [
        {
            "metadata": {"name": "payment-service", "namespace": "argocd"},
            "status": {
                "sync": {"status": "OutOfSync"},
                "health": {"status": "Healthy"},
            },
        },
        {
            "metadata": {"name": "auth-service", "namespace": "argocd"},
            "status": {
                "sync": {"status": "Synced"},
                "health": {"status": "Degraded"},
            },
        },
    ]
    drift_events = _drift_detector.analyze_argocd_apps(argocd_apps)
    results.append(f"GitOps drift: detected {len(drift_events)} drift events")

    # 8. K8s health check
    pods = [
        {
            "metadata": {"name": "api-pod-abc", "namespace": "default",
                         "labels": {"app": "api-gateway"}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "api",
                    "ready": True,
                    "restartCount": 15,
                    "state": {"running": {}},
                }],
            },
        },
        {
            "metadata": {"name": "worker-pod-xyz", "namespace": "default",
                         "labels": {"app": "worker"}},
            "status": {
                "phase": "Running",
                "containerStatuses": [{
                    "name": "worker",
                    "ready": True,
                    "restartCount": 0,
                    "state": {"waiting": {"reason": "CrashLoopBackOff", "message": "Exit code 137"}},
                }],
            },
        },
    ]
    pod_issues = _health_monitor.analyze_pods(pods)
    results.append(f"K8s health: found {len(pod_issues)} workload issues")

    # 9. Predictive scaling
    metrics = [
        {"cpu_utilization": 0.45, "memory_utilization": 0.50},
        {"cpu_utilization": 0.52, "memory_utilization": 0.55},
        {"cpu_utilization": 0.60, "memory_utilization": 0.62},
        {"cpu_utilization": 0.68, "memory_utilization": 0.70},
        {"cpu_utilization": 0.75, "memory_utilization": 0.78},
        {"cpu_utilization": 0.82, "memory_utilization": 0.85},
    ]
    rec = _predictor.predict_and_recommend("api-gateway", "default", 3, metrics)
    if rec:
        results.append(f"Scaling: {rec.action} api-gateway to {rec.recommended_replicas} replicas ({rec.urgency} urgency)")

    return {
        "demo": "IntelliPipeline Demo Seeded",
        "results": results,
        "summary": {
            "vulnerabilities_found": len(vuln_findings),
            "secrets_found": len(secret_findings),
            "config_issues": len(config_findings),
            "cves_found": len(dep_findings),
            "risk_score": round(risk["score"], 0),
            "deploy_decision": risk["decision"],
            "optimizer_suggestions": len(suggestions),
            "gitops_drift_events": len(drift_events),
            "k8s_issues": len(pod_issues),
            "scaling_action_needed": rec is not None,
        },
    }


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  IntelliPipeline v{SERVICE_VERSION}")
    print(f"  AI-Native CI/CD Autopilot")
    print(f"{'='*60}")
    print(f"  API:  http://localhost:{PORT}")
    print(f"  Docs: http://localhost:{PORT}/docs")
    print(f"  Demo: POST http://localhost:{PORT}/api/v1/demo/seed")
    print(f"{'='*60}\n")
    uvicorn.run("dev_server:app", host="0.0.0.0", port=PORT, reload=True)

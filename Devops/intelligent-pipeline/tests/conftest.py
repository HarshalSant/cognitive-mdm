"""Shared test fixtures for IntelliPipeline."""

import pytest
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
from core.event_bus import EventBus
from core.orchestrator import PipelineOrchestrator


@pytest.fixture
def vuln_scanner():
    return VulnerabilityScanner()


@pytest.fixture
def secret_scanner():
    return SecretScanner()


@pytest.fixture
def config_auditor():
    return ConfigAuditor()


@pytest.fixture
def dep_scanner():
    return DependencyScanner()


@pytest.fixture
def bug_fixer():
    return BugFixer()


@pytest.fixture
def optimizer():
    return PipelineOptimizer()


@pytest.fixture
def pr_generator():
    return PRGenerator()


@pytest.fixture
def risk_scorer():
    return RiskScorer()


@pytest.fixture
def drift_detector():
    return DriftDetector()


@pytest.fixture
def health_monitor():
    return KubernetesHealthMonitor()


@pytest.fixture
def predictor():
    return PredictiveScaler()


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def orchestrator(vuln_scanner, secret_scanner, config_auditor, dep_scanner, risk_scorer):
    return PipelineOrchestrator(
        vuln_scanner=vuln_scanner,
        secret_scanner=secret_scanner,
        config_auditor=config_auditor,
        dep_scanner=dep_scanner,
        risk_scorer=risk_scorer,
    )


@pytest.fixture
def sql_injection_code():
    return 'cursor.execute("SELECT * FROM users WHERE id = " + user_id)'


@pytest.fixture
def safe_code():
    return 'cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))'


@pytest.fixture
def secret_code():
    return 'GITHUB_TOKEN = "ghp_abc123DEF456ghi789JKL012mno345pqr678"'


@pytest.fixture
def bad_dockerfile():
    return """FROM ubuntu:latest
USER root
ENV DB_PASSWORD=supersecret123
COPY . .
RUN pip install -r requirements.txt
EXPOSE 22
CMD ["python", "app.py"]
"""


@pytest.fixture
def good_dockerfile():
    return """FROM python:3.11-slim@sha256:abc123
RUN adduser --disabled-password --gecos '' appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER appuser
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "app.py"]
"""


@pytest.fixture
def vulnerable_deps():
    return [
        {"name": "pyyaml", "version": "5.4.0", "ecosystem": "python"},
        {"name": "django", "version": "3.2.0", "ecosystem": "python"},
        {"name": "log4j-core", "version": "2.14.0", "ecosystem": "java"},
    ]


@pytest.fixture
def safe_deps():
    return [
        {"name": "pyyaml", "version": "6.0.1", "ecosystem": "python"},
        {"name": "django", "version": "4.2.0", "ecosystem": "python"},
        {"name": "requests", "version": "2.31.0", "ecosystem": "python"},
    ]


@pytest.fixture
def metrics_trending_up():
    return [
        {"cpu_utilization": 0.30, "memory_utilization": 0.35},
        {"cpu_utilization": 0.40, "memory_utilization": 0.42},
        {"cpu_utilization": 0.52, "memory_utilization": 0.55},
        {"cpu_utilization": 0.65, "memory_utilization": 0.68},
        {"cpu_utilization": 0.75, "memory_utilization": 0.79},
        {"cpu_utilization": 0.83, "memory_utilization": 0.86},
    ]


@pytest.fixture
def metrics_stable_low():
    return [
        {"cpu_utilization": 0.10, "memory_utilization": 0.15},
        {"cpu_utilization": 0.12, "memory_utilization": 0.14},
        {"cpu_utilization": 0.11, "memory_utilization": 0.16},
        {"cpu_utilization": 0.09, "memory_utilization": 0.13},
    ]

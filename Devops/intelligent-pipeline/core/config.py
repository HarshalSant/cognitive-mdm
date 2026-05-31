"""
Central configuration for IntelliPipeline.
All env-var overrides and constants live here.
"""

from __future__ import annotations

import os

# ---- Service identity -------------------------------------------------------
SERVICE_NAME = "intelligent-pipeline"
SERVICE_VERSION = "1.0.0"
PORT = int(os.environ.get("INTELLIPIPELINE_PORT", "9001"))

# ---- LLM --------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2048"))

# ---- Git integrations -------------------------------------------------------
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "")
JENKINS_URL = os.environ.get("JENKINS_URL", "http://jenkins:8080")
JENKINS_USER = os.environ.get("JENKINS_USER", "admin")
JENKINS_TOKEN = os.environ.get("JENKINS_TOKEN", "")

# ---- Kubernetes / GitOps ----------------------------------------------------
KUBECONFIG_PATH = os.environ.get("KUBECONFIG", "~/.kube/config")
ARGOCD_URL = os.environ.get("ARGOCD_URL", "http://argocd-server:80")
ARGOCD_TOKEN = os.environ.get("ARGOCD_TOKEN", "")
FLUX_NAMESPACE = os.environ.get("FLUX_NAMESPACE", "flux-system")

# ---- Risk thresholds --------------------------------------------------------
RISK_AUTO_DEPLOY_MAX = float(os.environ.get("RISK_AUTO_DEPLOY_MAX", "30"))
RISK_CANARY_MAX = float(os.environ.get("RISK_CANARY_MAX", "65"))
RISK_BLOCK_MIN = float(os.environ.get("RISK_BLOCK_MIN", "85"))

# ---- Scanner ----------------------------------------------------------------
VULN_CRITICAL_BLOCK = os.environ.get("VULN_CRITICAL_BLOCK", "true").lower() == "true"
SECRET_SCAN_ENABLED = os.environ.get("SECRET_SCAN_ENABLED", "true").lower() == "true"
DEPENDENCY_SCAN_ENABLED = os.environ.get("DEPENDENCY_SCAN_ENABLED", "true").lower() == "true"

# ---- Build optimizer --------------------------------------------------------
OPTIMIZER_MIN_SAVINGS_SECONDS = int(os.environ.get("OPTIMIZER_MIN_SAVINGS_SECONDS", "30"))

# ---- Source trust weights (same pattern as cognitive-mdm) -------------------
SOURCE_TRUST: dict[str, float] = {
    "github_push": 0.85,
    "github_pr": 0.90,
    "gitlab_push": 0.85,
    "jenkins_trigger": 0.75,
    "manual": 0.70,
    "scheduled": 0.80,
}

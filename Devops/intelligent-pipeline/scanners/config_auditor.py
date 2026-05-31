"""
Configuration Auditor -- detects misconfigurations in:
  - Dockerfile
  - GitHub Actions / GitLab CI / Jenkinsfile
  - Helm values.yaml
  - Kubernetes manifests
  - docker-compose.yml
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ConfigFinding:
    rule_id: str
    title: str
    severity: str
    blocking: bool
    config_type: str
    line_number: int
    line_content: str
    remediation: str
    cis_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "blocking": self.blocking,
            "config_type": self.config_type,
            "line_number": self.line_number,
            "line_content": self.line_content.strip()[:120],
            "remediation": self.remediation,
            "cis_ref": self.cis_ref,
        }


# ---- Dockerfile rules -------------------------------------------------------

DOCKERFILE_RULES: list[dict[str, Any]] = [
    {
        "id": "D001", "title": "Unpinned base image",
        "severity": "HIGH", "blocking": False,
        "pattern": r"^FROM\s+[^\s:@]+(?::latest)?\s*$",
        "remediation": "Pin base images to a specific digest: FROM ubuntu@sha256:...",
        "cis_ref": "CIS Docker 4.1",
    },
    {
        "id": "D002", "title": "Running as root user",
        "severity": "HIGH", "blocking": True,
        "pattern": r"^USER\s+root\s*$",
        "remediation": "Create a non-root user: RUN adduser -D appuser && USER appuser",
        "cis_ref": "CIS Docker 4.1",
    },
    {
        "id": "D003", "title": "No USER directive (runs as root by default)",
        "severity": "MEDIUM", "blocking": False,
        "check": "no_user_directive",
        "remediation": "Add USER nonroot before CMD/ENTRYPOINT",
        "cis_ref": "CIS Docker 4.1",
    },
    {
        "id": "D004", "title": "ADD used instead of COPY",
        "severity": "LOW", "blocking": False,
        "pattern": r"^ADD\s+(?!https?://)",
        "remediation": "Use COPY instead of ADD unless you need tar auto-extraction or URL fetching",
    },
    {
        "id": "D005", "title": "Secrets passed as ENV variables",
        "severity": "CRITICAL", "blocking": True,
        "pattern": r"^ENV\s+.*(PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY)\s*=\s*\S+",
        "remediation": "Use Docker secrets or build-time secrets (RUN --mount=type=secret)",
    },
    {
        "id": "D006", "title": "No HEALTHCHECK defined",
        "severity": "LOW", "blocking": False,
        "check": "no_healthcheck",
        "remediation": "Add HEALTHCHECK CMD curl -f http://localhost/ || exit 1",
    },
    {
        "id": "D007", "title": "apt-get update without version pinning",
        "severity": "MEDIUM", "blocking": False,
        "pattern": r"apt-get\s+install\s+(?!.*=)",
        "remediation": "Pin package versions: apt-get install -y package=1.2.3",
    },
    {
        "id": "D008", "title": "EXPOSE on sensitive port",
        "severity": "MEDIUM", "blocking": False,
        "pattern": r"^EXPOSE\s+(22|23|3389|5432|3306|27017|6379)\b",
        "remediation": "Avoid exposing administrative/database ports. Use internal networking instead.",
    },
    {
        "id": "D009", "title": "Privileged COPY from root",
        "severity": "MEDIUM", "blocking": False,
        "pattern": r"^COPY\s+--chown=root",
        "remediation": "Use a non-root owner for copied files",
    },
    {
        "id": "D010", "title": "pip install without --no-cache-dir",
        "severity": "LOW", "blocking": False,
        "pattern": r"pip\s+install(?!.*--no-cache-dir)",
        "remediation": "Use pip install --no-cache-dir to reduce image size",
    },
]

# ---- CI YAML rules ----------------------------------------------------------

CI_RULES: list[dict[str, Any]] = [
    {
        "id": "C001", "title": "Unpinned GitHub Action (uses @main or @master)",
        "severity": "HIGH", "blocking": False,
        "pattern": r"uses:\s+[^@]+@(main|master|HEAD)",
        "remediation": "Pin actions to a full commit SHA: uses: actions/checkout@a81bbbf8298c0fa03ea29cdc473d45769f953675",
    },
    {
        "id": "C002", "title": "Secrets exposed in environment variables",
        "severity": "HIGH", "blocking": True,
        "pattern": r"env:\s*\n\s+\w+:\s*\$\{\{.*secrets\.",
        "remediation": "Restrict secret exposure to the steps that need them, not at job level",
    },
    {
        "id": "C003", "title": "No job timeout defined",
        "severity": "MEDIUM", "blocking": False,
        "check": "no_timeout",
        "remediation": "Set timeout-minutes: 30 on each job to prevent runaway builds",
    },
    {
        "id": "C004", "title": "Privileged container in CI",
        "severity": "HIGH", "blocking": True,
        "pattern": r"privileged:\s*true",
        "remediation": "Avoid privileged containers in CI. Use specific capabilities instead.",
    },
    {
        "id": "C005", "title": "Pull request from fork can access secrets",
        "severity": "HIGH", "blocking": False,
        "pattern": r"pull_request_target:",
        "remediation": "Use pull_request (not pull_request_target) for untrusted forks, or add explicit permission checks",
    },
    {
        "id": "C006", "title": "Broad write permissions granted",
        "severity": "MEDIUM", "blocking": False,
        "pattern": r"permissions:\s*write-all",
        "remediation": "Use least-privilege permissions. Specify only required permissions per job.",
    },
    {
        "id": "C007", "title": "Script injection via untrusted input",
        "severity": "CRITICAL", "blocking": True,
        "pattern": r"run:.*\$\{\{\s*(github\.event\.(issue|pull_request|comment)\.(title|body))",
        "remediation": "Never interpolate untrusted GitHub context into run: commands. Use an intermediate env var.",
    },
    {
        "id": "C008", "title": "Docker build without --no-cache in CI",
        "severity": "LOW", "blocking": False,
        "pattern": r"docker build(?!.*--no-cache)",
        "remediation": "Consider --no-cache or explicit cache-from for reproducible CI builds",
    },
]

# ---- Helm values rules ------------------------------------------------------

HELM_RULES: list[dict[str, Any]] = [
    {
        "id": "H001", "title": "No resource limits defined",
        "severity": "HIGH", "blocking": False,
        "check": "no_resource_limits",
        "remediation": "Set resources.limits.cpu and resources.limits.memory for all containers",
    },
    {
        "id": "H002", "title": "Privileged security context",
        "severity": "CRITICAL", "blocking": True,
        "pattern": r"privileged:\s*true",
        "remediation": "Remove privileged: true. Use specific capabilities with securityContext.capabilities.add",
    },
    {
        "id": "H003", "title": "No liveness/readiness probes",
        "severity": "MEDIUM", "blocking": False,
        "check": "no_probes",
        "remediation": "Add livenessProbe and readinessProbe to all containers",
    },
    {
        "id": "H004", "title": "Image tag set to latest",
        "severity": "HIGH", "blocking": False,
        "pattern": r"tag:\s*latest",
        "remediation": "Pin image tags to specific versions or digests",
    },
    {
        "id": "H005", "title": "allowPrivilegeEscalation not disabled",
        "severity": "HIGH", "blocking": False,
        "check": "privilege_escalation",
        "remediation": "Set securityContext.allowPrivilegeEscalation: false",
    },
    {
        "id": "H006", "title": "Running as root (runAsNonRoot not set)",
        "severity": "HIGH", "blocking": True,
        "check": "run_as_root",
        "remediation": "Set securityContext.runAsNonRoot: true and securityContext.runAsUser: 1000",
    },
    {
        "id": "H007", "title": "No replica count > 1 for production",
        "severity": "MEDIUM", "blocking": False,
        "pattern": r"replicaCount:\s*[01]\b",
        "remediation": "Set replicaCount to at least 2 for production workloads",
    },
]


class ConfigAuditor:
    """
    Multi-format config auditor.
    Auto-detects config type from content; all rules are pure-Python, no deps.
    """

    def __init__(self) -> None:
        self._dockerfile_compiled = self._compile(DOCKERFILE_RULES)
        self._ci_compiled = self._compile(CI_RULES)
        self._helm_compiled = self._compile(HELM_RULES)

    def _compile(self, rules: list[dict]) -> list[dict]:
        out = []
        for r in rules:
            entry = dict(r)
            if "pattern" in r:
                entry["re"] = re.compile(r["pattern"], re.IGNORECASE | re.MULTILINE)
            out.append(entry)
        return out

    def audit(self, content: str, config_type: str | None = None) -> list[dict[str, Any]]:
        if config_type is None:
            config_type = self._detect_type(content)
        if config_type == "dockerfile":
            return self._audit_dockerfile(content)
        if config_type in ("github_actions", "gitlab_ci", "ci_yaml"):
            return self._audit_ci(content)
        if config_type in ("helm_values", "helm"):
            return self._audit_helm(content)
        # Try all
        findings = []
        for ct, fn in [("dockerfile", self._audit_dockerfile), ("ci_yaml", self._audit_ci), ("helm", self._audit_helm)]:
            f = fn(content)
            if f:
                findings.extend(f)
        return findings

    def _detect_type(self, content: str) -> str:
        if re.search(r"^FROM\s+\S+", content, re.MULTILINE):
            return "dockerfile"
        if "jobs:" in content and "steps:" in content:
            return "github_actions"
        if "stages:" in content and "script:" in content:
            return "gitlab_ci"
        if "replicaCount:" in content or "image:\n" in content:
            return "helm_values"
        return "unknown"

    def _audit_dockerfile(self, content: str) -> list[dict[str, Any]]:
        lines = content.splitlines()
        findings: list[ConfigFinding] = []
        has_user = any(re.match(r"^USER\s+(?!root)", l, re.IGNORECASE) for l in lines)
        has_healthcheck = any(l.strip().startswith("HEALTHCHECK") for l in lines)

        for rule in self._dockerfile_compiled:
            check = rule.get("check")
            if check == "no_user_directive" and not has_user:
                findings.append(ConfigFinding(
                    rule_id=rule["id"], title=rule["title"],
                    severity=rule["severity"], blocking=rule["blocking"],
                    config_type="dockerfile", line_number=0,
                    line_content="", remediation=rule["remediation"],
                    cis_ref=rule.get("cis_ref", ""),
                ))
                continue
            if check == "no_healthcheck" and not has_healthcheck:
                findings.append(ConfigFinding(
                    rule_id=rule["id"], title=rule["title"],
                    severity=rule["severity"], blocking=rule["blocking"],
                    config_type="dockerfile", line_number=0,
                    line_content="", remediation=rule["remediation"],
                ))
                continue
            if "re" not in rule:
                continue
            for i, line in enumerate(lines, 1):
                if rule["re"].search(line):
                    findings.append(ConfigFinding(
                        rule_id=rule["id"], title=rule["title"],
                        severity=rule["severity"], blocking=rule["blocking"],
                        config_type="dockerfile", line_number=i,
                        line_content=line, remediation=rule["remediation"],
                        cis_ref=rule.get("cis_ref", ""),
                    ))
        return [f.to_dict() for f in findings]

    def _audit_ci(self, content: str) -> list[dict[str, Any]]:
        lines = content.splitlines()
        findings: list[ConfigFinding] = []
        has_timeout = "timeout-minutes:" in content

        for rule in self._ci_compiled:
            if rule.get("check") == "no_timeout" and not has_timeout:
                findings.append(ConfigFinding(
                    rule_id=rule["id"], title=rule["title"],
                    severity=rule["severity"], blocking=rule["blocking"],
                    config_type="ci_yaml", line_number=0,
                    line_content="", remediation=rule["remediation"],
                ))
                continue
            if "re" not in rule:
                continue
            for i, line in enumerate(lines, 1):
                if rule["re"].search(line):
                    findings.append(ConfigFinding(
                        rule_id=rule["id"], title=rule["title"],
                        severity=rule["severity"], blocking=rule["blocking"],
                        config_type="ci_yaml", line_number=i,
                        line_content=line, remediation=rule["remediation"],
                    ))
        return [f.to_dict() for f in findings]

    def _audit_helm(self, content: str) -> list[dict[str, Any]]:
        lines = content.splitlines()
        findings: list[ConfigFinding] = []
        has_limits = "limits:" in content
        has_probes = "livenessProbe:" in content or "readinessProbe:" in content
        has_nonroot = "runAsNonRoot: true" in content
        has_no_privilege_escalation = "allowPrivilegeEscalation: false" in content

        checks = {
            "no_resource_limits": not has_limits,
            "no_probes": not has_probes,
            "run_as_root": not has_nonroot,
            "privilege_escalation": not has_no_privilege_escalation,
        }
        for rule in self._helm_compiled:
            check = rule.get("check")
            if check and checks.get(check, False):
                findings.append(ConfigFinding(
                    rule_id=rule["id"], title=rule["title"],
                    severity=rule["severity"], blocking=rule["blocking"],
                    config_type="helm", line_number=0,
                    line_content="", remediation=rule["remediation"],
                ))
                continue
            if "re" not in rule:
                continue
            for i, line in enumerate(lines, 1):
                if rule["re"].search(line):
                    findings.append(ConfigFinding(
                        rule_id=rule["id"], title=rule["title"],
                        severity=rule["severity"], blocking=rule["blocking"],
                        config_type="helm", line_number=i,
                        line_content=line, remediation=rule["remediation"],
                    ))
        return [f.to_dict() for f in findings]

    def audit_with_fix(self, content: str, config_type: str | None = None) -> dict[str, Any]:
        findings = self.audit(content, config_type)
        fixed_content = content
        applied_fixes: list[str] = []

        if config_type == "dockerfile" or self._detect_type(content) == "dockerfile":
            fixed_content, applied_fixes = self._auto_fix_dockerfile(content)

        return {
            "findings": findings,
            "fixed_content": fixed_content,
            "applied_fixes": applied_fixes,
            "finding_count": len(findings),
        }

    def _auto_fix_dockerfile(self, content: str) -> tuple[str, list[str]]:
        lines = content.splitlines()
        fixes: list[str] = []
        out = []
        has_user = any(re.match(r"^USER\s+", l, re.IGNORECASE) for l in lines)

        for i, line in enumerate(lines):
            out.append(line)
            if not has_user and re.match(r"^(CMD|ENTRYPOINT)", line, re.IGNORECASE):
                out.insert(-1, "USER nonroot")
                fixes.append("Inserted USER nonroot before CMD/ENTRYPOINT")
                has_user = True
            if re.match(r"^FROM\s+\S+:latest", line, re.IGNORECASE):
                out[-1] = re.sub(r":latest", ":stable", line)
                fixes.append(f"Changed :latest tag to :stable on line {i+1}")

        return "\n".join(out), fixes

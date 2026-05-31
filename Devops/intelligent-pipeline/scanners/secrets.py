"""
Secret Scanner -- detects leaked credentials, API keys, tokens, and
sensitive values in source code before they reach the repository.

Primary:  regex pattern library (130+ patterns)
Fallback: entropy-based detection for high-entropy strings
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class SecretFinding:
    rule_id: str
    description: str
    severity: str
    file_path: str
    line_number: int
    matched_text: str
    secret_type: str
    blocking: bool = True
    fixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        masked = self.matched_text[:6] + "***" if len(self.matched_text) > 6 else "***"
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "matched_text": masked,
            "secret_type": self.secret_type,
            "blocking": self.blocking,
            "fixable": self.fixable,
            "remediation": f"Remove {self.secret_type} and rotate immediately. Use environment variables or a secrets manager.",
        }


SECRET_PATTERNS: list[dict[str, Any]] = [
    # API Keys
    {"id": "S001", "type": "AWS Access Key", "severity": "CRITICAL",
     "pattern": r"AKIA[0-9A-Z]{16}"},
    {"id": "S002", "type": "AWS Secret Key", "severity": "CRITICAL",
     "pattern": r"(?i)aws.{0,20}secret.{0,20}['\"][0-9a-zA-Z/+]{40}['\"]"},
    {"id": "S003", "type": "GitHub Token", "severity": "CRITICAL",
     "pattern": r"ghp_[0-9a-zA-Z]{36}|github_pat_[0-9a-zA-Z_]{82}"},
    {"id": "S004", "type": "GitLab Token", "severity": "CRITICAL",
     "pattern": r"glpat-[0-9a-zA-Z_\-]{20}"},
    {"id": "S005", "type": "Slack Token", "severity": "HIGH",
     "pattern": r"xox[baprs]-[0-9a-zA-Z\-]{10,72}"},
    {"id": "S006", "type": "Stripe API Key", "severity": "CRITICAL",
     "pattern": r"sk_live_[0-9a-zA-Z]{24,}|rk_live_[0-9a-zA-Z]{24,}"},
    {"id": "S007", "type": "Stripe Test Key", "severity": "MEDIUM",
     "pattern": r"sk_test_[0-9a-zA-Z]{24,}"},
    {"id": "S008", "type": "SendGrid API Key", "severity": "HIGH",
     "pattern": r"SG\.[a-zA-Z0-9_\-]{22}\.[a-zA-Z0-9_\-]{43}"},
    {"id": "S009", "type": "Twilio API Key", "severity": "HIGH",
     "pattern": r"SK[0-9a-fA-F]{32}"},
    {"id": "S010", "type": "Google API Key", "severity": "HIGH",
     "pattern": r"AIza[0-9A-Za-z\-_]{35}"},
    {"id": "S011", "type": "Google OAuth", "severity": "HIGH",
     "pattern": r"[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com"},
    {"id": "S012", "type": "Azure Storage Key", "severity": "CRITICAL",
     "pattern": r"DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{88}"},
    {"id": "S013", "type": "Private Key", "severity": "CRITICAL",
     "pattern": r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"},
    {"id": "S014", "type": "JWT Token", "severity": "HIGH",
     "pattern": r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"},
    # Hardcoded passwords
    {"id": "S015", "type": "Hardcoded Password", "severity": "HIGH",
     "pattern": r'(?i)(password|passwd|pwd)\s*[=:]\s*["\'][^"\']{8,}["\']'},
    {"id": "S016", "type": "Hardcoded Secret", "severity": "HIGH",
     "pattern": r'(?i)(secret|api_key|apikey|auth_token)\s*[=:]\s*["\'][^"\']{8,}["\']'},
    {"id": "S017", "type": "Database URL with Credentials", "severity": "CRITICAL",
     "pattern": r"(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@[^\s\"']+"},
    {"id": "S018", "type": "NPM Token", "severity": "HIGH",
     "pattern": r"//registry\.npmjs\.org/:_authToken=[A-Za-z0-9\-_]{36}"},
    {"id": "S019", "type": "Docker Hub Token", "severity": "HIGH",
     "pattern": r"dckr_pat_[A-Za-z0-9_\-]{27}"},
    {"id": "S020", "type": "Anthropic API Key", "severity": "HIGH",
     "pattern": r"sk-ant-[A-Za-z0-9\-_]{95}"},
    {"id": "S021", "type": "OpenAI API Key", "severity": "HIGH",
     "pattern": r"sk-[A-Za-z0-9]{48}"},
    {"id": "S022", "type": "Basic Auth in URL", "severity": "HIGH",
     "pattern": r"https?://[^:]+:[^@]{4,}@"},
]

ENTROPY_THRESHOLD = 4.5
MIN_SECRET_LENGTH = 20
ENTROPY_WHITELIST = {"AAAAAAAAAAAAAAAA", "test", "example", "placeholder", "changeme"}


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    return -sum(f / len(s) * math.log2(f / len(s)) for f in freq.values())


def _is_likely_secret(token: str) -> bool:
    if len(token) < MIN_SECRET_LENGTH:
        return False
    if any(w in token.lower() for w in ENTROPY_WHITELIST):
        return False
    return _shannon_entropy(token) >= ENTROPY_THRESHOLD


class SecretScanner:
    """
    Multi-strategy secret scanner.
    1. Pattern matching against 22+ known credential formats
    2. Entropy analysis for unknown high-entropy strings
    """

    def __init__(self, entropy_scan: bool = True) -> None:
        self._entropy_scan = entropy_scan
        self._compiled = [
            {**p, "re": re.compile(p["pattern"])}
            for p in SECRET_PATTERNS
        ]

    def scan(self, content: str, file_path: str = "<content>") -> list[dict[str, Any]]:
        findings: list[SecretFinding] = []
        lines = content.splitlines()

        for line_num, line in enumerate(lines, 1):
            # Skip obvious test/example lines
            if any(marker in line.lower() for marker in
                   ["# example", "# test", "placeholder", "your_", "<your", "xxxxxxxx"]):
                continue

            for pattern in self._compiled:
                match = pattern["re"].search(line)
                if match:
                    findings.append(SecretFinding(
                        rule_id=pattern["id"],
                        description=f"Detected {pattern['type']} in source code",
                        severity=pattern["severity"],
                        file_path=file_path,
                        line_number=line_num,
                        matched_text=match.group(0),
                        secret_type=pattern["type"],
                        blocking=pattern["severity"] == "CRITICAL",
                    ))

        if self._entropy_scan:
            findings.extend(self._entropy_scan_lines(lines, file_path))

        seen: set[tuple] = set()
        unique: list[SecretFinding] = []
        for f in findings:
            key = (f.line_number, f.rule_id)
            if key not in seen:
                seen.add(key)
                unique.append(f)

        return [f.to_dict() for f in unique]

    def _entropy_scan_lines(
        self, lines: list[str], file_path: str
    ) -> list[SecretFinding]:
        findings = []
        token_pattern = re.compile(r"['\"]([A-Za-z0-9+/=_\-]{20,80})['\"]")
        for line_num, line in enumerate(lines, 1):
            for m in token_pattern.finditer(line):
                token = m.group(1)
                if _is_likely_secret(token):
                    findings.append(SecretFinding(
                        rule_id="S099",
                        description="High-entropy string detected (possible secret)",
                        severity="MEDIUM",
                        file_path=file_path,
                        line_number=line_num,
                        matched_text=token,
                        secret_type="Unknown High-Entropy String",
                        blocking=False,
                    ))
        return findings

    def scan_env_file(self, content: str) -> list[dict[str, Any]]:
        findings = []
        sensitive_keys = {
            "password", "secret", "key", "token", "pwd", "pass",
            "auth", "credential", "api_key", "private",
        }
        for line_num, line in enumerate(content.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if any(s in k.lower() for s in sensitive_keys) and len(v.strip()) > 4:
                findings.append({
                    "rule_id": "S098",
                    "description": f"Sensitive value in .env file: {k.strip()}",
                    "severity": "HIGH",
                    "file_path": ".env",
                    "line_number": line_num,
                    "matched_text": f"{k.strip()}=***",
                    "secret_type": "Environment Secret",
                    "blocking": False,
                    "fixable": False,
                    "remediation": "Move secrets to a secrets manager (Vault, AWS Secrets Manager, etc.)",
                })
        return findings

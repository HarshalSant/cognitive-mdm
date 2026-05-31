"""
AI Bug Fixer -- generates code patches for failing builds and known vulnerabilities.

Primary:  Claude API (when ANTHROPIC_API_KEY is set)
Fallback: Rule-based patch templates for common vulnerability patterns
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")


@dataclass
class PatchResult:
    finding_id: str
    original_line: str
    fixed_line: str
    explanation: str
    confidence: float
    method: str
    line_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "original_line": self.original_line,
            "fixed_line": self.fixed_line,
            "explanation": self.explanation,
            "confidence": round(self.confidence, 3),
            "method": self.method,
            "line_number": self.line_number,
        }


# ---- Rule-based fix templates -----------------------------------------------

RULE_FIXES: dict[str, dict[str, Any]] = {
    "V001": {
        "description": "SQL injection -- use parameterised query",
        "transform": lambda line: re.sub(
            r'execute\s*\(\s*f"(.*?)\{([^}]+)\}(.*?)"\s*\)',
            r'execute("\1%s\3", (\2,))',
            line,
        ),
        "confidence": 0.75,
    },
    "V002": {
        "description": "Command injection -- remove shell=True",
        "transform": lambda line: line.replace("shell=True", "shell=False"),
        "confidence": 0.80,
    },
    "V006": {
        "description": "Insecure YAML load -- use safe_load",
        "transform": lambda line: line.replace("yaml.load(", "yaml.safe_load("),
        "confidence": 0.95,
    },
    "V007": {
        "description": "Weak hash -- upgrade to sha256",
        "transform": lambda line: re.sub(r"hashlib\.(md5|sha1)\s*\(", "hashlib.sha256(", line),
        "confidence": 0.92,
    },
    "V012": {
        "description": "Debug mode -- disable in production",
        "transform": lambda line: re.sub(r"debug\s*=\s*True", "debug=False", line, flags=re.IGNORECASE),
        "confidence": 0.88,
    },
    "D001": {
        "description": "Dockerfile -- pin base image tag",
        "transform": lambda line: re.sub(r"(:latest)\s*$", ":stable", line),
        "confidence": 0.70,
    },
    "D002": {
        "description": "Dockerfile -- change root to nonroot",
        "transform": lambda line: re.sub(r"USER\s+root", "USER nonroot", line, flags=re.IGNORECASE),
        "confidence": 0.90,
    },
}


def _rule_based_fix(finding: dict[str, Any]) -> PatchResult | None:
    rule_id = finding.get("rule_id", "")
    fix_rule = RULE_FIXES.get(rule_id)
    if not fix_rule:
        return None

    original = finding.get("line_content", "")
    if not original:
        return None

    try:
        fixed = fix_rule["transform"](original)
        if fixed == original:
            return None
        return PatchResult(
            finding_id=rule_id,
            original_line=original,
            fixed_line=fixed,
            explanation=fix_rule["description"],
            confidence=fix_rule["confidence"],
            method="rule_based",
            line_number=finding.get("line_number", 0),
        )
    except Exception:
        return None


class BugFixer:
    """
    LLM-powered bug fixer with rule-based fallback.
    Generates targeted patches for identified vulnerabilities and build failures.
    """

    def __init__(self) -> None:
        self._client = None
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            except ImportError:
                logger.warning("bug_fixer.anthropic_not_installed")

    async def fix(
        self,
        finding: dict[str, Any],
        source_code: str = "",
    ) -> dict[str, Any] | None:
        rule_fix = _rule_based_fix(finding)

        if not self._client:
            return rule_fix.to_dict() if rule_fix else None

        prompt = f"""You are a security-focused code repair engineer.

Finding:
{json.dumps(finding, indent=2)}

Relevant source code (excerpt):
```
{source_code[:2000]}
```

Generate a minimal, targeted fix for this specific finding.
Respond with JSON only:
{{
  "finding_id": "{finding.get('rule_id', '')}",
  "original_line": "exact original line",
  "fixed_line": "corrected line",
  "explanation": "one sentence explaining the fix",
  "confidence": 0.0-1.0,
  "method": "llm"
}}"""

        try:
            import anthropic
            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            result["line_number"] = finding.get("line_number", 0)
            return result
        except Exception as e:
            logger.warning("bug_fixer.llm_fallback", error=str(e))
            return rule_fix.to_dict() if rule_fix else None

    async def fix_build_failure(
        self,
        error_log: str,
        source_files: dict[str, str],
    ) -> dict[str, Any]:
        """Analyse a build/test failure log and suggest fixes."""
        if not self._client:
            return _rule_based_build_fix(error_log)

        file_summary = {k: v[:500] for k, v in list(source_files.items())[:3]}
        prompt = f"""You are an expert DevOps engineer analysing a CI/CD build failure.

Build error log:
```
{error_log[:3000]}
```

Relevant source files:
{json.dumps(file_summary, indent=2)}

Diagnose the failure and provide fixes.
Respond with JSON:
{{
  "root_cause": "concise explanation",
  "error_type": "ImportError|SyntaxError|TestFailure|BuildError|TypeMismatch|Other",
  "affected_files": ["list of files to fix"],
  "fixes": [
    {{
      "file": "filename",
      "original": "original code snippet",
      "replacement": "fixed code snippet",
      "explanation": "why this fixes it"
    }}
  ],
  "confidence": 0.0-1.0
}}"""

        try:
            import anthropic
            response = await self._client.messages.create(
                model=LLM_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            logger.warning("bug_fixer.build_fix_fallback", error=str(e))
            return _rule_based_build_fix(error_log)


def _rule_based_build_fix(error_log: str) -> dict[str, Any]:
    patterns = [
        (r"ModuleNotFoundError: No module named '([^']+)'",
         "missing_dependency",
         lambda m: f"Install missing package: pip install {m.group(1)}"),
        (r"SyntaxError: ([^\n]+)",
         "syntax_error",
         lambda m: f"Fix syntax error: {m.group(1)}"),
        (r"ImportError: cannot import name '([^']+)' from '([^']+)'",
         "import_error",
         lambda m: f"Symbol '{m.group(1)}' not found in '{m.group(2)}'. Check API changes."),
        (r"AssertionError: ([^\n]*)",
         "test_failure",
         lambda m: f"Test assertion failed: {m.group(1)[:100]}"),
        (r"TypeError: ([^\n]+)",
         "type_error",
         lambda m: f"Type mismatch: {m.group(1)[:100]}"),
        (r"PermissionError: ([^\n]+)",
         "permission_error",
         lambda m: f"Permission denied: {m.group(1)[:80]}. Check file/directory permissions."),
    ]

    for pattern, error_type, fix_fn in patterns:
        m = re.search(pattern, error_log)
        if m:
            return {
                "root_cause": fix_fn(m),
                "error_type": error_type,
                "affected_files": [],
                "fixes": [],
                "confidence": 0.55,
                "method": "rule_based",
            }

    return {
        "root_cause": "Unable to automatically diagnose failure -- manual review required",
        "error_type": "Unknown",
        "affected_files": [],
        "fixes": [],
        "confidence": 0.0,
        "method": "rule_based",
    }

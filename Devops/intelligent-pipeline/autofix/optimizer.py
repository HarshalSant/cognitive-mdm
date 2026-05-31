"""
Pipeline Optimizer -- analyses CI/CD pipeline YAML and build history to
identify waste, parallelization opportunities, and caching improvements.

Works on GitHub Actions, GitLab CI, and generic YAML pipelines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class OptimizationSuggestion:
    rule_id: str
    category: str
    title: str
    description: str
    impact: str
    estimated_savings_seconds: int
    priority: str
    auto_fixable: bool
    original_snippet: str = ""
    suggested_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "impact": self.impact,
            "estimated_savings_seconds": self.estimated_savings_seconds,
            "priority": self.priority,
            "auto_fixable": self.auto_fixable,
            "original_snippet": self.original_snippet,
            "suggested_snippet": self.suggested_snippet,
        }


class PipelineOptimizer:
    """
    Analyses pipeline YAML + historical run data to surface concrete
    optimisation suggestions with estimated time and cost savings.
    """

    def analyze(
        self,
        pipeline_yaml: str,
        build_history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        suggestions: list[OptimizationSuggestion] = []

        suggestions.extend(self._check_caching(pipeline_yaml))
        suggestions.extend(self._check_parallelism(pipeline_yaml))
        suggestions.extend(self._check_timeouts(pipeline_yaml))
        suggestions.extend(self._check_redundant_steps(pipeline_yaml))
        suggestions.extend(self._check_docker_layers(pipeline_yaml))
        suggestions.extend(self._check_test_splitting(pipeline_yaml, build_history))
        suggestions.extend(self._analyze_history(build_history))

        suggestions.sort(key=lambda s: s.estimated_savings_seconds, reverse=True)
        return [s.to_dict() for s in suggestions]

    def _check_caching(self, yaml: str) -> list[OptimizationSuggestion]:
        suggestions = []

        if "pip install" in yaml and "cache" not in yaml:
            suggestions.append(OptimizationSuggestion(
                rule_id="O001",
                category="caching",
                title="Add pip dependency cache",
                description="pip install runs without caching. Dependencies are re-downloaded on every run.",
                impact="Reduces install time by 60-80% on cache hits",
                estimated_savings_seconds=120,
                priority="HIGH",
                auto_fixable=True,
                original_snippet="- run: pip install -r requirements.txt",
                suggested_snippet=(
                    "- uses: actions/cache@v3\n"
                    "  with:\n"
                    "    path: ~/.cache/pip\n"
                    "    key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}\n"
                    "- run: pip install -r requirements.txt"
                ),
            ))

        if "npm install" in yaml and "cache" not in yaml:
            suggestions.append(OptimizationSuggestion(
                rule_id="O002",
                category="caching",
                title="Add npm dependency cache",
                description="npm install runs without caching. node_modules downloaded on every run.",
                impact="Reduces install time by 70-90% on cache hits",
                estimated_savings_seconds=180,
                priority="HIGH",
                auto_fixable=True,
                original_snippet="- run: npm install",
                suggested_snippet=(
                    "- uses: actions/cache@v3\n"
                    "  with:\n"
                    "    path: ~/.npm\n"
                    "    key: ${{ runner.os }}-node-${{ hashFiles('package-lock.json') }}\n"
                    "- run: npm ci"
                ),
            ))

        if "docker build" in yaml and "--cache-from" not in yaml:
            suggestions.append(OptimizationSuggestion(
                rule_id="O003",
                category="caching",
                title="Add Docker layer cache",
                description="Docker builds without layer caching rebuild all layers on every run.",
                impact="Reduces build time by 40-70% when layers unchanged",
                estimated_savings_seconds=240,
                priority="HIGH",
                auto_fixable=True,
                original_snippet="- run: docker build -t myapp .",
                suggested_snippet=(
                    "- run: |\n"
                    "    docker build \\\n"
                    "      --cache-from $IMAGE:latest \\\n"
                    "      --build-arg BUILDKIT_INLINE_CACHE=1 \\\n"
                    "      -t $IMAGE:${{ github.sha }} ."
                ),
            ))

        if ("mvn" in yaml or "gradle" in yaml) and "cache" not in yaml:
            suggestions.append(OptimizationSuggestion(
                rule_id="O004",
                category="caching",
                title="Add Maven/Gradle dependency cache",
                description="Java build tool downloads all dependencies on every run.",
                impact="Reduces dependency resolution time by 80-95%",
                estimated_savings_seconds=300,
                priority="HIGH",
                auto_fixable=True,
                original_snippet="- run: mvn package",
                suggested_snippet=(
                    "- uses: actions/cache@v3\n"
                    "  with:\n"
                    "    path: ~/.m2/repository\n"
                    "    key: ${{ runner.os }}-maven-${{ hashFiles('**/pom.xml') }}\n"
                    "- run: mvn package -DskipTests"
                ),
            ))

        return suggestions

    def _check_parallelism(self, yaml: str) -> list[OptimizationSuggestion]:
        suggestions = []

        test_count = yaml.count("pytest") + yaml.count("jest") + yaml.count("rspec")
        if test_count > 0 and "matrix:" not in yaml:
            suggestions.append(OptimizationSuggestion(
                rule_id="O010",
                category="parallelism",
                title="Parallelise test suite with matrix strategy",
                description="Tests run sequentially. Matrix strategy can split tests across runners.",
                impact="Reduce test time proportionally to number of runners",
                estimated_savings_seconds=180,
                priority="MEDIUM",
                auto_fixable=False,
                original_snippet="- run: pytest tests/",
                suggested_snippet=(
                    "strategy:\n"
                    "  matrix:\n"
                    "    shard: [1, 2, 3, 4]\n"
                    "steps:\n"
                    "  - run: pytest tests/ --shard=${{ matrix.shard }}/4"
                ),
            ))

        jobs = re.findall(r"^\s{2}([a-zA-Z_\-]+):\s*$", yaml, re.MULTILINE)
        needs = re.findall(r"needs:\s*\[([^\]]+)\]", yaml)
        if len(jobs) > 2 and not needs:
            suggestions.append(OptimizationSuggestion(
                rule_id="O011",
                category="parallelism",
                title="Jobs run sequentially -- add explicit parallelism",
                description=f"Found {len(jobs)} jobs with no 'needs:' dependencies. Independent jobs can run in parallel.",
                impact="Cut total pipeline time by running independent stages simultaneously",
                estimated_savings_seconds=120,
                priority="MEDIUM",
                auto_fixable=False,
            ))

        return suggestions

    def _check_timeouts(self, yaml: str) -> list[OptimizationSuggestion]:
        suggestions = []
        if "timeout-minutes:" not in yaml:
            suggestions.append(OptimizationSuggestion(
                rule_id="O020",
                category="reliability",
                title="No job timeout configured",
                description="Jobs without timeouts can run indefinitely, wasting CI minutes and blocking the queue.",
                impact="Prevents runaway builds from consuming resources",
                estimated_savings_seconds=0,
                priority="MEDIUM",
                auto_fixable=True,
                original_snippet="jobs:\n  build:\n    runs-on: ubuntu-latest",
                suggested_snippet="jobs:\n  build:\n    runs-on: ubuntu-latest\n    timeout-minutes: 30",
            ))
        return suggestions

    def _check_redundant_steps(self, yaml: str) -> list[OptimizationSuggestion]:
        suggestions = []

        checkout_count = yaml.count("actions/checkout")
        if checkout_count > 1:
            suggestions.append(OptimizationSuggestion(
                rule_id="O030",
                category="redundancy",
                title=f"Duplicate checkout steps ({checkout_count}x)",
                description="Repository checked out multiple times. Use job outputs or artifacts instead.",
                impact="Saves 5-15 seconds per duplicate checkout",
                estimated_savings_seconds=checkout_count * 10,
                priority="LOW",
                auto_fixable=False,
            ))

        install_count = yaml.count("pip install") + yaml.count("npm install")
        if install_count > 1:
            suggestions.append(OptimizationSuggestion(
                rule_id="O031",
                category="redundancy",
                title=f"Dependencies installed {install_count}x across jobs",
                description="Multiple jobs install the same dependencies. Use a shared cache or upload artifacts.",
                impact="Saves 30-120 seconds per redundant install",
                estimated_savings_seconds=(install_count - 1) * 60,
                priority="MEDIUM",
                auto_fixable=False,
            ))

        return suggestions

    def _check_docker_layers(self, yaml: str) -> list[OptimizationSuggestion]:
        suggestions = []
        if "COPY . ." in yaml or "COPY . /app" in yaml:
            suggestions.append(OptimizationSuggestion(
                rule_id="O040",
                category="docker",
                title="Suboptimal COPY order invalidates cache",
                description="Copying entire source before installing dependencies invalidates dependency cache on every code change.",
                impact="Fix layer ordering to restore dependency caching benefit",
                estimated_savings_seconds=90,
                priority="HIGH",
                auto_fixable=True,
                original_snippet="COPY . .\nRUN pip install -r requirements.txt",
                suggested_snippet="COPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .",
            ))
        return suggestions

    def _check_test_splitting(
        self, yaml: str, history: list[dict[str, Any]]
    ) -> list[OptimizationSuggestion]:
        suggestions = []
        if not history:
            return suggestions

        slow_runs = [r for r in history if r.get("duration_seconds", 0) > 600]
        if len(slow_runs) > 2:
            avg_duration = sum(r.get("duration_seconds", 0) for r in slow_runs) / len(slow_runs)
            suggestions.append(OptimizationSuggestion(
                rule_id="O050",
                category="performance",
                title="Consistently slow builds detected",
                description=f"Average build time {int(avg_duration)}s. Consider splitting into faster feedback loops.",
                impact="Faster PR feedback loop, lower CI cost",
                estimated_savings_seconds=int(avg_duration * 0.4),
                priority="HIGH",
                auto_fixable=False,
            ))
        return suggestions

    def _analyze_history(self, history: list[dict[str, Any]]) -> list[OptimizationSuggestion]:
        suggestions = []
        if not history:
            return suggestions

        flaky = [r for r in history if r.get("result") == "failed" and r.get("retry_count", 0) > 0]
        if len(flaky) > 2:
            suggestions.append(OptimizationSuggestion(
                rule_id="O060",
                category="flakiness",
                title=f"Flaky tests detected ({len(flaky)} retried runs)",
                description="Tests that fail intermittently slow the pipeline and erode confidence. Identify and quarantine them.",
                impact="Remove non-deterministic failures from critical path",
                estimated_savings_seconds=len(flaky) * 45,
                priority="HIGH",
                auto_fixable=False,
            ))

        return suggestions

    def estimate_monthly_savings(
        self, suggestions: list[dict[str, Any]], runs_per_day: int = 20
    ) -> dict[str, Any]:
        total_savings_seconds = sum(s.get("estimated_savings_seconds", 0) for s in suggestions)
        monthly_seconds = total_savings_seconds * runs_per_day * 30
        monthly_minutes = monthly_seconds / 60
        estimated_cost_saving = monthly_minutes * 0.008
        return {
            "per_run_savings_seconds": total_savings_seconds,
            "monthly_savings_minutes": round(monthly_minutes, 0),
            "estimated_monthly_cost_saving_usd": round(estimated_cost_saving, 2),
            "based_on_runs_per_day": runs_per_day,
        }

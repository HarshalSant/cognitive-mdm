"""Tests for pipeline optimizer."""

import pytest
from autofix.optimizer import PipelineOptimizer


class TestPipelineOptimizer:
    def test_detects_missing_pip_cache(self, optimizer):
        yaml = "- run: pip install -r requirements.txt"
        suggestions = optimizer.analyze(yaml, [])
        assert any(s["rule_id"] == "O001" for s in suggestions)

    def test_detects_missing_npm_cache(self, optimizer):
        yaml = "- run: npm install"
        suggestions = optimizer.analyze(yaml, [])
        assert any(s["rule_id"] == "O002" for s in suggestions)

    def test_detects_missing_docker_cache(self, optimizer):
        yaml = "- run: docker build -t myapp ."
        suggestions = optimizer.analyze(yaml, [])
        assert any(s["rule_id"] == "O003" for s in suggestions)

    def test_detects_no_timeout(self, optimizer):
        yaml = "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi"
        suggestions = optimizer.analyze(yaml, [])
        assert any(s["rule_id"] == "O020" for s in suggestions)

    def test_detects_wrong_copy_order(self, optimizer):
        yaml = "COPY . .\nRUN pip install -r requirements.txt"
        suggestions = optimizer.analyze(yaml, [])
        assert any(s["rule_id"] == "O040" for s in suggestions)

    def test_detects_flaky_builds(self, optimizer):
        history = [
            {"result": "failed", "retry_count": 2},
            {"result": "failed", "retry_count": 1},
            {"result": "failed", "retry_count": 3},
        ]
        suggestions = optimizer.analyze("- run: pytest", history)
        assert any(s["rule_id"] == "O060" for s in suggestions)

    def test_no_suggestions_for_good_pipeline(self, optimizer):
        yaml = """
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: pip-${{ hashFiles('requirements.txt') }}
      - run: pip install -r requirements.txt
      - run: pytest tests/
"""
        suggestions = optimizer.analyze(yaml, [])
        cache_suggestions = [s for s in suggestions if s["rule_id"] in ("O001", "O020")]
        assert len(cache_suggestions) == 0

    def test_suggestions_sorted_by_savings(self, optimizer):
        yaml = "- run: pip install\n- run: npm install\n- run: docker build .\n- run: pytest"
        suggestions = optimizer.analyze(yaml, [])
        if len(suggestions) > 1:
            savings = [s["estimated_savings_seconds"] for s in suggestions]
            assert savings == sorted(savings, reverse=True)

    def test_monthly_savings_calculation(self, optimizer):
        suggestions = [
            {"estimated_savings_seconds": 120},
            {"estimated_savings_seconds": 240},
        ]
        savings = optimizer.estimate_monthly_savings(suggestions, runs_per_day=20)
        assert savings["per_run_savings_seconds"] == 360
        assert savings["monthly_savings_minutes"] > 0
        assert savings["estimated_monthly_cost_saving_usd"] >= 0

    def test_auto_fixable_flagged(self, optimizer):
        yaml = "- run: pip install -r requirements.txt"
        suggestions = optimizer.analyze(yaml, [])
        pip_suggestions = [s for s in suggestions if s["rule_id"] == "O001"]
        assert all(s["auto_fixable"] for s in pip_suggestions)

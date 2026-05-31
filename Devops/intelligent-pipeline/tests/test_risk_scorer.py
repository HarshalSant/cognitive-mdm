"""Tests for pre-deploy risk scorer."""

import pytest
from risk.scorer import RiskScorer, _decision_from_score
from core.orchestrator import DeployDecision


class TestRiskScorer:
    def test_clean_feature_branch_low_risk(self, risk_scorer):
        result = risk_scorer.score(branch="feature/my-feature", findings=[])
        assert result["score"] < 50
        assert result["decision"] in ("approve", "canary")

    def test_prod_branch_higher_risk(self, risk_scorer):
        result_prod = risk_scorer.score(branch="main", findings=[])
        result_feat = risk_scorer.score(branch="feature/x", findings=[])
        assert result_prod["score"] > result_feat["score"]

    def test_critical_findings_raise_risk(self, risk_scorer):
        critical_findings = [
            {"severity": "CRITICAL", "blocking": True, "rule_id": "V001"},
            {"severity": "CRITICAL", "blocking": True, "rule_id": "V002"},
        ]
        result = risk_scorer.score(branch="feature/x", findings=critical_findings)
        assert result["score"] > 40

    def test_infra_file_changes_raise_risk(self, risk_scorer):
        result = risk_scorer.score(
            branch="feature/x",
            findings=[],
            files_changed=["k8s/deployment.yaml", "terraform/main.tf"],
        )
        result_no_infra = risk_scorer.score(branch="feature/x", findings=[])
        assert result["score"] > result_no_infra["score"]

    def test_auth_path_changes_raise_risk(self, risk_scorer):
        result = risk_scorer.score(
            branch="main",
            findings=[],
            files_changed=["auth/models.py", "security/middleware.py"],
        )
        assert result["score"] > 40

    def test_bad_history_raises_risk(self, risk_scorer):
        bad_history = [
            {"result": "failed"}, {"result": "failed"}, {"result": "failed"},
            {"result": "failed"}, {"result": "passed"},
        ]
        result_bad = risk_scorer.score(branch="feature/x", findings=[], build_history=bad_history)
        result_good = risk_scorer.score(branch="feature/x", findings=[])
        assert result_bad["score"] > result_good["score"]

    def test_score_has_all_dimensions(self, risk_scorer):
        result = risk_scorer.score(branch="main", findings=[])
        dim_names = {d["name"] for d in result["dimensions"]}
        assert {"branch_risk", "finding_risk", "change_risk", "history_risk", "blast_radius"}.issubset(dim_names)

    def test_result_has_recommendations(self, risk_scorer):
        result = risk_scorer.score(branch="main", findings=[
            {"severity": "CRITICAL", "blocking": True}
        ])
        assert len(result["recommendations"]) > 0

    def test_high_risk_score_gets_hold_or_block(self, risk_scorer):
        many_critical = [{"severity": "CRITICAL", "blocking": True}] * 10
        result = risk_scorer.score(
            branch="main",
            findings=many_critical,
            files_changed=["auth/models.py", "requirements.txt", "Dockerfile"],
            service_count=8, user_count=100000,
        )
        assert result["decision"] in ("hold", "block")

    def test_score_bounded_0_100(self, risk_scorer):
        result = risk_scorer.score(
            branch="main",
            findings=[{"severity": "CRITICAL"}] * 50,
            files_changed=["auth/security.py"] * 20,
            service_count=20, user_count=1000000,
        )
        assert 0 <= result["score"] <= 100


class TestDecisionThresholds:
    def test_low_score_approves(self):
        assert _decision_from_score(20).value == "approve"

    def test_medium_score_canary(self):
        assert _decision_from_score(55).value == "canary"

    def test_high_score_hold(self):
        assert _decision_from_score(75).value == "hold"

    def test_critical_score_block(self):
        assert _decision_from_score(90).value == "block"

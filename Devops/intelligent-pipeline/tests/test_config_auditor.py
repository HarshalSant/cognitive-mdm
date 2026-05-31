"""Tests for configuration auditor."""

import pytest
from scanners.config_auditor import ConfigAuditor


class TestDockerfileAuditor:
    def test_flags_latest_tag(self, config_auditor, bad_dockerfile):
        findings = config_auditor.audit(bad_dockerfile, "dockerfile")
        assert any(f["rule_id"] == "D001" for f in findings)

    def test_flags_root_user(self, config_auditor, bad_dockerfile):
        findings = config_auditor.audit(bad_dockerfile, "dockerfile")
        assert any(f["rule_id"] == "D002" for f in findings)

    def test_flags_secret_env(self, config_auditor, bad_dockerfile):
        findings = config_auditor.audit(bad_dockerfile, "dockerfile")
        assert any(f["rule_id"] == "D005" for f in findings)

    def test_flags_sensitive_port(self, config_auditor, bad_dockerfile):
        findings = config_auditor.audit(bad_dockerfile, "dockerfile")
        assert any(f["rule_id"] == "D008" for f in findings)

    def test_flags_no_healthcheck(self, config_auditor, bad_dockerfile):
        findings = config_auditor.audit(bad_dockerfile, "dockerfile")
        assert any(f["rule_id"] == "D006" for f in findings)

    def test_clean_dockerfile_fewer_issues(self, config_auditor, good_dockerfile):
        findings = config_auditor.audit(good_dockerfile, "dockerfile")
        blocking = [f for f in findings if f.get("blocking")]
        assert len(blocking) == 0

    def test_auto_detection_dockerfile(self, config_auditor, bad_dockerfile):
        findings = config_auditor.audit(bad_dockerfile)
        assert len(findings) > 0

    def test_audit_with_fix_returns_fixed_content(self, config_auditor, bad_dockerfile):
        result = config_auditor.audit_with_fix(bad_dockerfile, "dockerfile")
        assert "fixed_content" in result
        assert "applied_fixes" in result

    def test_all_findings_have_remediation(self, config_auditor, bad_dockerfile):
        findings = config_auditor.audit(bad_dockerfile, "dockerfile")
        assert all(f.get("remediation") for f in findings)


class TestCIYAMLAuditor:
    def test_flags_unpinned_action(self, config_auditor):
        yaml = "      - uses: actions/checkout@main"
        findings = config_auditor.audit(yaml, "github_actions")
        assert any(f["rule_id"] == "C001" for f in findings)

    def test_flags_privileged_container(self, config_auditor):
        yaml = "        privileged: true"
        findings = config_auditor.audit(yaml, "github_actions")
        assert any(f["rule_id"] == "C004" for f in findings)

    def test_flags_no_timeout(self, config_auditor):
        yaml = "jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi"
        findings = config_auditor.audit(yaml, "github_actions")
        assert any(f["rule_id"] == "C003" for f in findings)

    def test_flags_script_injection(self, config_auditor):
        yaml = '          run: echo "${{ github.event.issue.title }}"'
        findings = config_auditor.audit(yaml, "github_actions")
        assert any(f["rule_id"] == "C007" for f in findings)


class TestHelmAuditor:
    def test_flags_no_resource_limits(self, config_auditor):
        yaml = "replicaCount: 2\nimage:\n  tag: latest"
        findings = config_auditor.audit(yaml, "helm_values")
        assert any(f["rule_id"] == "H001" for f in findings)

    def test_flags_privileged_helm(self, config_auditor):
        yaml = "replicaCount: 2\nsecurityContext:\n  privileged: true"
        findings = config_auditor.audit(yaml, "helm_values")
        assert any(f["rule_id"] == "H002" for f in findings)

    def test_flags_latest_tag_helm(self, config_auditor):
        yaml = "image:\n  repository: myapp\n  tag: latest"
        findings = config_auditor.audit(yaml, "helm_values")
        assert any(f["rule_id"] == "H004" for f in findings)

"""Tests for dependency CVE scanner."""

import pytest
from scanners.dependency import DependencyScanner, _version_below


class TestVersionComparison:
    def test_older_version_is_below(self):
        assert _version_below("3.2.0", "3.2.18") is True

    def test_same_version_not_below(self):
        assert _version_below("3.2.18", "3.2.18") is False

    def test_newer_version_not_below(self):
        assert _version_below("4.0.0", "3.2.18") is False

    def test_major_version_difference(self):
        assert _version_below("2.14.0", "2.17.1") is True


class TestDependencyScanner:
    def test_detects_vulnerable_pyyaml(self, dep_scanner):
        deps = [{"name": "pyyaml", "version": "5.4.0", "ecosystem": "python"}]
        findings = dep_scanner.scan(deps)
        assert len(findings) > 0
        assert any(f["cve"] == "CVE-2020-14343" for f in findings)
        assert any(f["severity"] == "CRITICAL" for f in findings)

    def test_detects_log4shell(self, dep_scanner):
        deps = [{"name": "log4j-core", "version": "2.14.0", "ecosystem": "java"}]
        findings = dep_scanner.scan(deps)
        assert any(f["cve"] == "CVE-2021-44228" for f in findings)
        assert any(f["severity"] == "CRITICAL" for f in findings)

    def test_detects_spring4shell(self, dep_scanner):
        deps = [{"name": "spring-core", "version": "5.3.1", "ecosystem": "java"}]
        findings = dep_scanner.scan(deps)
        assert any(f["cve"] == "CVE-2022-22965" for f in findings)

    def test_safe_versions_no_findings(self, dep_scanner, safe_deps):
        findings = dep_scanner.scan(safe_deps)
        assert len(findings) == 0

    def test_multiple_vulns_same_package(self, dep_scanner):
        deps = [{"name": "django", "version": "3.1.0", "ecosystem": "python"}]
        findings = dep_scanner.scan(deps)
        assert len(findings) >= 1

    def test_parse_requirements_txt(self, dep_scanner):
        content = "django==3.2.0\nrequests==2.28.0\npyyaml==5.4.0\n# comment\n-r base.txt"
        deps = dep_scanner.parse_requirements_txt(content)
        names = [d["name"] for d in deps]
        assert "django" in names
        assert "pyyaml" in names
        assert all(d["ecosystem"] == "python" for d in deps)

    def test_parse_package_json(self, dep_scanner):
        content = '{"dependencies": {"lodash": "4.17.15", "express": "4.18.0"}}'
        deps = dep_scanner.parse_package_json(content)
        names = [d["name"] for d in deps]
        assert "lodash" in names

    def test_finding_has_remediation(self, dep_scanner, vulnerable_deps):
        findings = dep_scanner.scan(vulnerable_deps)
        assert all(f.get("remediation") for f in findings)

    def test_critical_blocking(self, dep_scanner, vulnerable_deps):
        findings = dep_scanner.scan(vulnerable_deps)
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        assert all(f["blocking"] for f in critical)

    def test_summary_includes_critical_cves(self, dep_scanner, vulnerable_deps):
        findings = dep_scanner.scan(vulnerable_deps)
        summary = dep_scanner.get_summary(findings)
        assert "critical_cves" in summary
        assert "upgrade_required" in summary

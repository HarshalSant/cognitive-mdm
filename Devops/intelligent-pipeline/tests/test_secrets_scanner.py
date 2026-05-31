"""Tests for secret detection scanner."""

import pytest
from scanners.secrets import SecretScanner, _shannon_entropy, _is_likely_secret


class TestSecretScanner:
    def test_detects_github_token(self, secret_scanner, secret_code):
        findings = secret_scanner.scan(secret_code)
        assert any(f["secret_type"] == "GitHub Token" for f in findings)
        assert any(f["severity"] == "CRITICAL" for f in findings)

    def test_detects_aws_access_key(self, secret_scanner):
        code = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"'
        findings = secret_scanner.scan(code)
        assert any("AWS" in f["secret_type"] for f in findings)

    def test_detects_private_key_header(self, secret_scanner):
        code = "-----BEGIN RSA PRIVATE KEY-----"
        findings = secret_scanner.scan(code)
        assert any(f["severity"] == "CRITICAL" for f in findings)

    def test_detects_database_url_with_creds(self, secret_scanner):
        code = 'DB = "postgres://admin:password123@db.internal:5432/prod"'
        findings = secret_scanner.scan(code)
        assert any("Database" in f["secret_type"] for f in findings)

    def test_detects_hardcoded_password(self, secret_scanner):
        code = 'password = "myS3cur3P@ssw0rd"'
        findings = secret_scanner.scan(code)
        assert len(findings) > 0

    def test_skips_placeholder_values(self, secret_scanner):
        code = '# example: API_KEY = "your_api_key_here"'
        findings = secret_scanner.scan(code)
        assert len(findings) == 0

    def test_masked_output(self, secret_scanner, secret_code):
        findings = secret_scanner.scan(secret_code)
        for f in findings:
            assert "***" in f["matched_text"]

    def test_blocking_for_critical(self, secret_scanner, secret_code):
        findings = secret_scanner.scan(secret_code)
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        assert all(f["blocking"] for f in critical)

    def test_env_file_scan(self, secret_scanner):
        env_content = """
DB_HOST=localhost
DB_PASSWORD=secretpassword123
API_KEY=my_api_key_value
LOG_LEVEL=info
"""
        findings = secret_scanner.scan_env_file(env_content)
        assert len(findings) > 0
        keys = [f["matched_text"].split("=")[0] for f in findings]
        assert any("PASSWORD" in k.upper() or "API_KEY" in k.upper() for k in keys)

    def test_empty_content_no_findings(self, secret_scanner):
        findings = secret_scanner.scan("")
        assert findings == []

    def test_remediation_in_findings(self, secret_scanner, secret_code):
        findings = secret_scanner.scan(secret_code)
        assert all(f.get("remediation") for f in findings)


class TestEntropyDetection:
    def test_high_entropy_string(self):
        assert _shannon_entropy("aB3$kL9@mN2!xP7^") > 3.5

    def test_low_entropy_string(self):
        assert _shannon_entropy("aaaaaaaaaaaaaaaa") < 1.0

    def test_empty_string_zero_entropy(self):
        assert _shannon_entropy("") == 0.0

    def test_is_likely_secret_long_random(self):
        assert _is_likely_secret("aB3kL9mN2xP7qR5wS8tU1vW4yZ0") is True

    def test_is_likely_secret_short_string(self):
        assert _is_likely_secret("short") is False

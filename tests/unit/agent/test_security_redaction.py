"""Unit tests for secret redaction in model agent exchange logs."""

from __future__ import annotations

from flight_agent_evaluator.agent.security import redact_secrets


def test_redact_api_key_strings():
    raw_str = "Authorization: sk-abc12345678901234567890 for API access"
    redacted = redact_secrets(raw_str)
    assert "sk-abc12345678901234567890" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_redact_project_and_service_account_keys() -> None:
    for key in (
        "sk-proj-AbCdEf_0123456789-ghijklmnopQRST",
        "sk-svcacct-Z9y8X7w6V5u4T3s2R1q0_pon-mlk",
    ):
        redacted = redact_secrets(f"key={key}!")
        assert key not in redacted
        assert "proj-" not in redacted and "svcacct-" not in redacted


def test_redact_bearer_tokens():
    raw_str = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
    redacted = redact_secrets(raw_str)
    assert "[REDACTED_SECRET]" in redacted


def test_redact_sensitive_dict_keys():
    data = {
        "api_key": "my-secret-key-12345",
        "authorization": "Bearer secret-token-xyz",
        "user": "passenger_1",
        "nested": {
            "token": "tok_998877665544332211",
            "flight": "AS142",
        },
    }
    redacted = redact_secrets(data)
    assert redacted["api_key"] == "[REDACTED_SECRET]"
    assert redacted["authorization"] == "[REDACTED_SECRET]"
    assert redacted["user"] == "passenger_1"
    assert redacted["nested"]["token"] == "[REDACTED_SECRET]"
    assert redacted["nested"]["flight"] == "AS142"


def test_redact_custom_secrets():
    raw_str = "Connecting to https://custom-internal-host.com with token 9876543210123456"
    redacted = redact_secrets(raw_str, custom_secrets=["https://custom-internal-host.com"])
    assert "custom-internal-host.com" not in redacted
    assert "[REDACTED_SECRET]" in redacted

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


def test_identifiers_ending_in_sk_are_not_api_keys() -> None:
    # Found in the first live run: content-addressed ids "task-<sha256>" matched "sk-…".
    for text in (
        "task-71a77aaf471fe1c831710583f57bb0033cc8a7dbe54d5e5349685b27263c2a60",
        "desk-0123456789abcdefghijklmnop",
        "risk-assessment-0123456789abcdef",
    ):
        assert redact_secrets(text) == text
    assert redact_secrets("(sk-abc12345678901234567890)") == "([REDACTED_SECRET])"


def test_short_placeholder_api_keys_are_not_treated_as_secrets() -> None:
    # Local servers (Ollama, vLLM) accept any dummy key; a reply that merely mentions
    # the word must not be flagged as leaking it.
    text = "This answer was produced by a local ollama model."
    assert redact_secrets(text, custom_secrets=["ollama"]) == text
    long_key = "0123456789abcdef0123"
    assert long_key not in redact_secrets(f"key {long_key}", custom_secrets=[long_key])

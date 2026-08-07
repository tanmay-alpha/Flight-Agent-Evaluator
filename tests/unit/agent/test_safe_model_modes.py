"""Unit tests verifying safe model modes and credential guardrails."""

from __future__ import annotations

import pytest

from flight_agent_evaluator.agent.model_client import OpenAIResponsesModelClient


def test_openai_model_client_requires_allow_live_model():
    # Attempting live mode without --allow-live-model flag raises ValueError
    with pytest.raises(ValueError, match="requires explicit --allow-live-model flag"):
        OpenAIResponsesModelClient(mode="live", allow_live_model=False)


def test_openai_model_client_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is required"):
        OpenAIResponsesModelClient(mode="live", allow_live_model=True)

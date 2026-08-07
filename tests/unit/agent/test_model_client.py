"""Unit tests for model client implementations."""

from __future__ import annotations

import pytest

from flight_agent_evaluator.agent.model_client import (
    OpenAIResponsesModelClient,
    ReplayModelClient,
)
from flight_agent_evaluator.contracts.model import (
    ModelConfiguration,
    ModelExchange,
    ModelRequest,
    ModelResponse,
)


def test_replay_model_client_basic_execution():
    req = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id="p1",
        prompt_policy_version="1.0",
        prompt_digest="abc",
        turn_index=0,
        messages=[{"role": "user", "content": "hello"}],
        model_configuration=ModelConfiguration(),
    )
    resp = ModelResponse(role="assistant", content="world")
    ex = ModelExchange(
        turn_index=0,
        request=req,
        response=resp,
        request_fingerprint=req.canonical_fingerprint(),
        response_digest=resp.canonical_digest(),
    )
    client = ReplayModelClient([ex])
    assert client.provider == "replay"
    assert client.model_id == "gpt-4o-mini"
    res = pytest.importorskip("asyncio").run(client.create_completion(req))
    assert res.content == "world"


def test_openai_responses_model_client_mode_checks():
    with pytest.raises(ValueError, match="requires explicit --allow-live-model flag"):
        OpenAIResponsesModelClient(mode="live", allow_live_model=False)

"""Unit tests for SHA-256 model exchange fingerprinting and replay zero-network enforcement."""

from __future__ import annotations

import pytest

from flight_agent_evaluator.agent.model_client import ReplayModelClient
from flight_agent_evaluator.contracts.model import (
    ModelConfiguration,
    ModelExchange,
    ModelRequest,
    ModelResponse,
)


def test_replay_model_client_fingerprint_matching():
    req = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id="read_only_v1",
        prompt_policy_version="1.0.0",
        prompt_digest="abc",
        turn_index=0,
        messages=[{"role": "user", "content": "Query"}],
        model_configuration=ModelConfiguration(),
    )
    fp = req.canonical_fingerprint()
    resp = ModelResponse(role="assistant", content="Answer")

    exchange = ModelExchange(
        turn_index=0,
        request=req,
        response=resp,
        request_fingerprint=fp,
        response_digest=resp.canonical_digest(),
    )

    client = ReplayModelClient([exchange])
    assert client.provider == "replay"
    assert client.model_id == "gpt-4o-mini"

    # Exact match succeeds
    result = pytest.importorskip("asyncio").run(client.create_completion(req))
    assert result.content == "Answer"

    # Mismatched fingerprint raises error
    mismatched_req = req.model_copy(
        update={"turn_index": 0, "messages": [{"role": "user", "content": "Different Query"}]}
    )
    client.reset()
    with pytest.raises(RuntimeError, match="Replay fingerprint mismatch"):
        pytest.importorskip("asyncio").run(client.create_completion(mismatched_req))

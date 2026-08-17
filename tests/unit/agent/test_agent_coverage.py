"""Coverage tests for agent loop, model client, prompt, and security modules."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    OpenAIResponsesModelClient,
    ReplayModelClient,
)
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.agent.security import redact_secrets, scan_request_for_reference_leakage
from flight_agent_evaluator.contracts.model import (
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelExchange,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    PromptPolicy,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_default_registry


def _make_context():
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    id_factory = DeterministicIdFactory(scenario_id="test", scenario_version=1, seed=42)
    return RunContext(
        run_id=uuid.uuid4(),
        scenario_id="test",
        scenario_version=1,
        seed=42,
        clock=clock,
        id_factory=id_factory,
        tool_call_limit=5,
        time_limit_seconds=60,
        correlation_id="c1",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


def test_prompt_policy_canonical_digest():
    p = PromptPolicy(policy_id="test_p", version="1.0.0", content="Test prompt content")
    digest = p.canonical_digest()
    assert len(digest) == 64
    default_p = get_default_prompt_policy()
    assert len(default_p.canonical_digest()) == 64


def test_model_configuration_canonical_digest():
    cfg = ModelConfiguration(provider="openai", model_id="gpt-4o-mini", temperature=0.0)
    assert len(cfg.canonical_digest()) == 64


def test_model_exchange_manifest_digest():
    cfg = ModelConfiguration()
    manifest = ModelExchangeManifest(manifest_id="m1", model_configuration=cfg, exchanges=[])
    assert len(manifest.manifest_digest()) == 64


def test_replay_model_client_missing_exchange():
    client = ReplayModelClient([])
    req = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id="p1",
        prompt_policy_version="1.0",
        prompt_digest="abc",
        turn_index=0,
        messages=[],
        model_configuration=ModelConfiguration(),
    )
    with pytest.raises(RuntimeError, match="Replay error: No recorded model exchange"):
        asyncio.run(client.create_completion(req))


def test_openai_responses_model_client_replay_mode_rejection():
    client = OpenAIResponsesModelClient(mode="replay")
    req = ModelRequest(
        provider="openai",
        model_id="gpt-4o-mini",
        prompt_policy_id="p1",
        prompt_policy_version="1.0",
        prompt_digest="abc",
        turn_index=0,
        messages=[],
        model_configuration=ModelConfiguration(),
    )
    with pytest.raises(RuntimeError, match="requires ReplayModelClient"):
        asyncio.run(client.create_completion(req))


def test_openai_responses_model_client_errors(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-1234567890")
    client = OpenAIResponsesModelClient(mode="live", allow_live_model=True)
    mock_completions = AsyncMock()
    client._client = MagicMock()
    client._client.chat.completions.create = mock_completions

    req = ModelRequest(
        provider="openai",
        model_id="gpt-4o-mini",
        prompt_policy_id="p1",
        prompt_policy_version="1.0",
        prompt_digest="abc",
        turn_index=0,
        messages=[{"role": "user", "content": "hi"}],
        model_configuration=ModelConfiguration(),
    )

    # Auth error
    mock_completions.side_effect = openai.AuthenticationError(
        message="auth err", response=MagicMock(status_code=401), body=None
    )
    with pytest.raises(RuntimeError, match="authentication failed"):
        asyncio.run(client.create_completion(req))

    # Rate limit error
    mock_completions.side_effect = openai.RateLimitError(
        message="rate err", response=MagicMock(status_code=429), body=None
    )
    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        asyncio.run(client.create_completion(req))

    # Timeout error
    mock_completions.side_effect = openai.APITimeoutError(request=MagicMock())
    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(client.create_completion(req))

    # Connection error
    mock_completions.side_effect = openai.APIConnectionError(request=MagicMock())
    with pytest.raises(RuntimeError, match="connection failed"):
        asyncio.run(client.create_completion(req))

    # Generic error
    mock_completions.side_effect = ValueError("generic failure")
    with pytest.raises(RuntimeError, match="provider error"):
        asyncio.run(client.create_completion(req))


def test_model_agent_unknown_tool_and_invalid_arguments():
    task = AgentTask(
        task_id="t1",
        scenario_id="s1",
        public_request="Query status",
        allowed_tools=["flight.get_status"],
        max_turns=5,
        tool_call_limit=5,
    )
    prompt_policy = get_default_prompt_policy()
    model_config = ModelConfiguration()
    registry = build_default_registry()
    agent_helper = ModelToolCallingAgent(
        model_client=ReplayModelClient([]), prompt_policy=prompt_policy
    )
    openai_tools = agent_helper._convert_registry_to_openai_tools(registry, task.allowed_tools)

    req0 = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id=prompt_policy.policy_id,
        prompt_policy_version=prompt_policy.version,
        prompt_digest=prompt_policy.canonical_digest(),
        turn_index=0,
        messages=[
            {"role": "system", "content": prompt_policy.content},
            {"role": "user", "content": task.public_request},
        ],
        tools=openai_tools,
        model_configuration=model_config,
    )
    tc0 = ModelToolCall(call_id="tc-1", tool_name="unknown_tool_x", arguments={})
    resp0 = ModelResponse(
        role="assistant", content=None, tool_calls=[tc0], finish_reason="tool_calls"
    )
    ex0 = ModelExchange(
        turn_index=0,
        request=req0,
        response=resp0,
        request_fingerprint=req0.canonical_fingerprint(),
        response_digest=resp0.canonical_digest(),
    )

    req1 = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id=prompt_policy.policy_id,
        prompt_policy_version=prompt_policy.version,
        prompt_digest=prompt_policy.canonical_digest(),
        turn_index=1,
        messages=[
            {"role": "system", "content": prompt_policy.content},
            {"role": "user", "content": task.public_request},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc-1",
                        "type": "function",
                        "function": {"name": "unknown_tool_x", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc-1",
                "content": '{"error": "Unknown or unregistered tool requested"}',
            },
        ],
        tools=openai_tools,
        model_configuration=model_config,
    )
    tc1 = ModelToolCall(call_id="tc-2", tool_name="flight.get_status", arguments={})
    resp1 = ModelResponse(
        role="assistant", content=None, tool_calls=[tc1], finish_reason="tool_calls"
    )
    ex1 = ModelExchange(
        turn_index=1,
        request=req1,
        response=resp1,
        request_fingerprint=req1.canonical_fingerprint(),
        response_digest=resp1.canonical_digest(),
    )

    req2 = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id=prompt_policy.policy_id,
        prompt_policy_version=prompt_policy.version,
        prompt_digest=prompt_policy.canonical_digest(),
        turn_index=2,
        messages=[
            {"role": "system", "content": prompt_policy.content},
            {"role": "user", "content": task.public_request},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc-1",
                        "type": "function",
                        "function": {"name": "unknown_tool_x", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc-1",
                "content": '{"error": "Unknown or unregistered tool requested"}',
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc-2",
                        "type": "function",
                        "function": {"name": "flight.get_status", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc-2",
                "content": '{"error": "Invalid tool arguments: Missing required parameter \'flight_id\'"}',
            },
        ],
        tools=openai_tools,
        model_configuration=model_config,
    )
    resp2 = ModelResponse(role="assistant", content="Could not find flight.", finish_reason="stop")
    ex2 = ModelExchange(
        turn_index=2,
        request=req2,
        response=resp2,
        request_fingerprint=req2.canonical_fingerprint(),
        response_digest=resp2.canonical_digest(),
    )

    client = ReplayModelClient([ex0, ex1, ex2])
    agent = ModelToolCallingAgent(model_client=client, prompt_policy=prompt_policy)

    provider = FixtureFlightProvider()
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    journal = HashChainJournal()
    executor = ToolExecutor(registry=registry, clock=clock, journal=journal, provider=provider)
    context = _make_context()

    res = asyncio.run(
        agent.execute(
            task=task,
            executor=executor,
            state=StateSnapshot(),
            context=context,
        )
    )

    assert res.stop_reason == AgentStopReason.COMPLETED
    assert res.invalid_tool_call_count == 2


def test_security_redaction_edge_cases():
    assert redact_secrets(None) is None
    assert redact_secrets(123) == 123
    assert redact_secrets(("a", "b")) == ("a", "b")
    empty_scan = scan_request_for_reference_leakage(
        ModelRequest(
            provider="replay",
            model_id="m",
            prompt_policy_id="p",
            prompt_policy_version="1",
            prompt_digest="d",
            turn_index=0,
            messages=[],
            model_configuration=ModelConfiguration(),
        ),
        ["", "a"],
    )
    assert len(empty_scan) == 0

"""Regression tests proving zero reference-answer leakage to ModelRequest."""

from __future__ import annotations

import asyncio
import datetime
import uuid

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import ReplayModelClient
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.agent.security import scan_request_for_reference_leakage
from flight_agent_evaluator.contracts.model import (
    AgentTask,
    ModelConfiguration,
    ModelExchange,
    ModelRequest,
    ModelResponse,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_default_registry

SECRET_ORACLE_FINAL_RESPONSE = "SECRET_MARKER_ORACLE_FINAL_RESPONSE_12345"
SECRET_HIDDEN_ASSERTION = "SECRET_MARKER_HIDDEN_ASSERTION_67890"
SECRET_VALID_TRAJECTORY = "SECRET_MARKER_VALID_TRAJECTORY_99999"


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


def test_reference_answer_marker_absence():
    task = AgentTask(
        task_id="t1",
        scenario_id="s1",
        public_request="What is the status of AS142?",
        allowed_tools=["flight.get_status"],
    )

    prompt_policy = get_default_prompt_policy()
    model_config = ModelConfiguration()
    registry = build_default_registry()
    agent_helper = ModelToolCallingAgent(
        model_client=ReplayModelClient([]), prompt_policy=prompt_policy
    )
    openai_tools = agent_helper._convert_registry_to_openai_tools(registry, task.allowed_tools)

    dummy_req = ModelRequest(
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
    dummy_resp = ModelResponse(role="assistant", content="AS142 is on time.")
    exchange = ModelExchange(
        turn_index=0,
        request=dummy_req,
        response=dummy_resp,
        request_fingerprint=dummy_req.canonical_fingerprint(),
        response_digest=dummy_resp.canonical_digest(),
    )

    client = ReplayModelClient([exchange])
    agent = ModelToolCallingAgent(model_client=client, prompt_policy=prompt_policy)

    provider = FixtureFlightProvider()
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    journal = HashChainJournal()
    executor = ToolExecutor(registry=registry, clock=clock, journal=journal, provider=provider)
    context = _make_context()

    asyncio.run(
        agent.execute(
            task=task,
            executor=executor,
            state=StateSnapshot(),
            context=context,
        )
    )

    history = client.exchange_history
    assert len(history) == 1
    req = history[0].request

    violations = scan_request_for_reference_leakage(
        req,
        [
            SECRET_ORACLE_FINAL_RESPONSE,
            SECRET_HIDDEN_ASSERTION,
            SECRET_VALID_TRAJECTORY,
        ],
    )
    assert len(violations) == 0, f"Found leakage violations: {violations}"

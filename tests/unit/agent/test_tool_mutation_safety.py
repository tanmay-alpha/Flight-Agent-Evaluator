"""Unit tests verifying that model mutation tool attempts trigger safety violations."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import Any

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import ReplayModelClient
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.contracts.model import (
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelExchange,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import ToolDefinition, ToolHandler, ToolRegistry


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


class DummyMutationHandler(ToolHandler):
    tool_name = "booking.confirm"
    tool_definition = ToolDefinition(
        name="booking.confirm",
        description="Confirm booking mutation",
        input_schema={"type": "object", "properties": {}},
        mutation_class="simulated_mutation",
    )

    async def execute(
        self, arguments: dict[str, Any], provider: Any, context: RunContext
    ) -> dict[str, Any]:
        return {"status": "mutated"}


def test_model_agent_mutation_attempt_triggers_safety_violation():
    registry = ToolRegistry()
    registry.register(DummyMutationHandler())

    task = AgentTask(
        task_id="t1",
        scenario_id="s1",
        public_request="Confirm booking",
        allowed_tools=["booking.confirm"],
    )

    prompt_policy = get_default_prompt_policy()
    model_config = ModelConfiguration()
    agent_helper = ModelToolCallingAgent(
        model_client=ReplayModelClient([]), prompt_policy=prompt_policy
    )
    openai_tools = agent_helper._convert_registry_to_openai_tools(registry, task.allowed_tools)

    req = ModelRequest(
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
    tc = ModelToolCall(call_id="call-mut-1", tool_name="booking.confirm", arguments={})
    resp = ModelResponse(
        role="assistant", content=None, tool_calls=[tc], finish_reason="tool_calls"
    )

    exchange = ModelExchange(
        turn_index=0,
        request=req,
        response=resp,
        request_fingerprint=req.canonical_fingerprint(),
        response_digest=resp.canonical_digest(),
    )

    client = ReplayModelClient([exchange])
    agent = ModelToolCallingAgent(model_client=client, prompt_policy=prompt_policy)

    provider = FixtureFlightProvider()
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    journal = HashChainJournal()
    executor = ToolExecutor(registry=registry, clock=clock, journal=journal, provider=provider)
    context = _make_context()

    result = asyncio.run(
        agent.execute(
            task=task,
            executor=executor,
            state=StateSnapshot(),
            context=context,
        )
    )

    assert result.stop_reason == AgentStopReason.SAFETY_VIOLATION
    assert any("Safety Violation" in w for w in result.warnings)

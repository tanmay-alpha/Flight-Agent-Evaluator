"""Unit tests for ModelAgentDriver LLM loop."""

from __future__ import annotations

import asyncio
import datetime
import uuid

from flight_agent_evaluator.agent.loop import ModelAgentDriver
from flight_agent_evaluator.agent.model_client import ModelClient, ModelExchange
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


def test_model_agent_driver_execution_loop():
    # Recorded exchange 1: call flight.get_status
    tc_exchange = ModelExchange(
        turn_index=0,
        request_messages=[],
        response_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc-1",
                    "type": "function",
                    "function": {
                        "name": "flight.get_status",
                        "arguments": '{"flight_number": "AS142"}',
                    },
                }
            ],
            "finish_reason": "tool_calls",
        },
    )

    # Recorded exchange 2: final answer
    final_exchange = ModelExchange(
        turn_index=1,
        request_messages=[],
        response_message={
            "role": "assistant",
            "content": "Flight AS142 is ON_TIME.",
            "tool_calls": None,
            "finish_reason": "stop",
        },
    )

    client = ModelClient(replay_mode=True, recorded_exchanges=[tc_exchange, final_exchange])
    driver = ModelAgentDriver(model_client=client)

    provider = FixtureFlightProvider()
    registry = build_default_registry()
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    journal = HashChainJournal()
    executor = ToolExecutor(registry=registry, clock=clock, journal=journal, provider=provider)
    context = _make_context()

    class DummyTrajectory:
        initial_query = "What is the status of AS142?"

    res = asyncio.run(
        driver.execute(
            trajectory=DummyTrajectory(),
            executor=executor,
            provider=provider,
            state=StateSnapshot(),
            tool_calls_remaining=5,
            context=context,
        )
    )

    assert res.tool_calls_made == 1
    assert res.final_response == "Flight AS142 is ON_TIME."
    assert len(res.model_exchanges) == 2

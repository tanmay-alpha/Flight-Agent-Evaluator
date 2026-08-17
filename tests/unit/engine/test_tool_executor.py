"""Tests for the tool executor and tool registry."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.fault_engine import FaultEngine
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.runtime.clock import VirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.tools.base import ToolDefinition, ToolRegistry


class _EchoProvider:
    """Minimal provider that echoes inputs back as a result."""

    async def get_flight_status(self, query):
        return {"flight_id": query.flight_identity.flight_number}

    async def search_flights(self, _request):
        return {"offers": []}


class _EchoHandler:
    """Minimal handler that uses the provider's get_flight_status method."""

    tool_name = "echo"

    def __init__(self):
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Echo",
        )

    async def execute(self, arguments, provider, context):
        return await provider.get_flight_status(arguments["query"])


def _make_context(seed: int = 42) -> RunContext:
    clock = VirtualClock()
    id_factory = DeterministicIdFactory(scenario_id="test", scenario_version=1, seed=seed)
    return RunContext(
        run_id=uuid.uuid4(),
        scenario_id="test",
        scenario_version=1,
        seed=seed,
        clock=clock,
        id_factory=id_factory,
        tool_call_limit=10,
        time_limit_seconds=60,
        correlation_id="c",
        scenario_digest="d",
        trajectory_digest="t",
    )


def _read_policy(context: RunContext, *tools: str) -> ExecutionToolPolicy:
    return ExecutionToolPolicy(
        scenario_id=context.scenario_id,
        allowed_tool_names=tools,
        allowed_mutation_classes=("read_only",),
    )


def test_executor_invokes_handler():
    registry = ToolRegistry()
    registry.register(_EchoHandler())
    provider: Any = _EchoProvider()
    context = _make_context()
    executor = ToolExecutor(
        registry, FaultEngine(()), provider=provider, execution_policy=_read_policy(context, "echo")
    )
    from flight_agent_evaluator.contracts.aviation import FlightIdentity, FlightStatusQuery

    query = FlightStatusQuery(
        flight_identity=FlightIdentity(
            flight_number="AS142",
            marketing_airline_iata="AS",
            operating_airline_iata="AS",
        ),
        query_date=datetime(2026, 7, 28, tzinfo=UTC),
    )
    call = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="echo",
        arguments={"query": query},
        start_time=context.clock.now(),
    )
    result = asyncio.run(executor.execute(call, context=context))
    assert result.status == "success"
    assert result.result == {"flight_id": "AS142"}


def test_executor_returns_failure_for_unknown_tool():
    registry = ToolRegistry()
    executor = ToolExecutor(registry, FaultEngine(()))
    context = _make_context()
    call = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="not.registered",
        arguments={},
        start_time=context.clock.now(),
    )
    result = asyncio.run(executor.execute(call, provider=None, context=context))
    assert result.status == "failure"
    assert result.error is not None
    assert result.error.error_type == "authorization_error"


def test_executor_handles_handler_exception():
    class _BrokenHandler:
        tool_name = "broken"

        def __init__(self):
            self.tool_definition = ToolDefinition(name=self.tool_name, description="broken")

        async def execute(self, arguments, provider, context):
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(_BrokenHandler())
    provider: Any = _EchoProvider()
    context = _make_context()
    executor = ToolExecutor(
        registry,
        FaultEngine(()),
        provider=provider,
        execution_policy=_read_policy(context, "broken"),
    )
    call = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="broken",
        arguments={},
        start_time=context.clock.now(),
    )
    result = asyncio.run(executor.execute(call, context=context))
    assert result.status == "failure"
    assert result.error is not None
    assert result.error.error_type == "internal_error"
    # Secure implementation: raw exception text is NOT leaked.
    assert "boom" not in result.error.message
    assert "unexpected" in result.error.message.lower()


def test_executor_enforces_tool_call_limit():
    from flight_agent_evaluator.contracts.aviation import FlightIdentity, FlightStatusQuery

    query = FlightStatusQuery(
        flight_identity=FlightIdentity(
            flight_number="AS142",
            marketing_airline_iata="AS",
            operating_airline_iata="AS",
        ),
        query_date=datetime(2026, 7, 28, tzinfo=UTC),
    )
    registry = ToolRegistry()
    registry.register(_EchoHandler())
    provider: Any = _EchoProvider()
    context = _make_context()
    executor = ToolExecutor(
        registry,
        FaultEngine(()),
        provider=provider,
        tool_call_limit=1,
        execution_policy=_read_policy(context, "echo"),
    )
    call = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="echo",
        arguments={"query": query},
        start_time=context.clock.now(),
    )
    # First call succeeds
    res1 = asyncio.run(executor.execute(call, context=context))
    assert res1.status == "success"

    # Second call fails due to tool call limit
    res2 = asyncio.run(executor.execute(call, context=context))
    assert res2.status == "failure"
    assert res2.error is not None
    assert res2.error.error_type == "invalid_arguments"


def test_identity_projector():
    from flight_agent_evaluator.engine.tool_executor import _IdentityProjector
    from flight_agent_evaluator.runtime.state import StateSnapshot

    projector = _IdentityProjector()
    initial_state = StateSnapshot(data={"existing": "val"})
    record = {"tool_name": "echo", "result": {"flight_id": "AS142"}}
    new_state = projector.apply(initial_state, record)
    assert isinstance(new_state, StateSnapshot)
    assert new_state.data["existing"] == "val"
    assert new_state.data["tool_call_summaries"] == [record]

    # Non-StateSnapshot input returned unchanged
    assert projector.apply({"raw": "dict"}, record) == {"raw": "dict"}


def test_scripted_agent_driver_execution():
    from flight_agent_evaluator.contracts.aviation import FlightIdentity, FlightStatusQuery
    from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver
    from flight_agent_evaluator.recording.contracts import (
        InvokeToolStep,
        ProduceFinalResponseStep,
        RecordCheckpointStep,
        ScriptedTrajectory,
    )
    from flight_agent_evaluator.runtime.state import StateSnapshot

    query = FlightStatusQuery(
        flight_identity=FlightIdentity(
            flight_number="AS142",
            marketing_airline_iata="AS",
            operating_airline_iata="AS",
        ),
        query_date=datetime(2026, 7, 28, tzinfo=UTC),
    )
    trajectory = ScriptedTrajectory(
        trajectory_id="traj-1",
        description="test trajectory",
        steps=(
            InvokeToolStep(step_id="s1", tool_name="echo", arguments={"query": query}),
            RecordCheckpointStep(step_id="s2", label="check1"),
            ProduceFinalResponseStep(step_id="s3", response="done"),
            InvokeToolStep(step_id="s4", tool_name="echo", arguments={"query": query}),
        ),
    )

    registry = ToolRegistry()
    registry.register(_EchoHandler())
    provider: Any = _EchoProvider()
    context = _make_context()
    executor = ToolExecutor(
        registry, FaultEngine(()), provider=provider, execution_policy=_read_policy(context, "echo")
    )
    driver = ScriptedAgentDriver()

    # With tool_calls_remaining = 1, first call succeeds, second skipped
    res = asyncio.run(
        driver.execute(
            trajectory=trajectory,
            executor=executor,
            provider=provider,
            state=StateSnapshot(),
            tool_calls_remaining=1,
            context=context,
        )
    )
    assert res.tool_calls_made == 1
    assert res.final_response == "done"
    assert res.checkpoints == ("check1",)

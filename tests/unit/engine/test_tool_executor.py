"""Tests for the tool executor and tool registry."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.contracts.tools import ToolCall
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


def test_executor_invokes_handler():
    registry = ToolRegistry()
    registry.register(_EchoHandler())
    provider: Any = _EchoProvider()
    executor = ToolExecutor(registry, FaultEngine(()), provider=provider)
    context = _make_context()
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
    assert result.error.error_type == "invalid_arguments"


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
    executor = ToolExecutor(registry, FaultEngine(()), provider=provider)
    context = _make_context()
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

"""Tests for the tool executor and tool registry."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

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

    async def search_flights(self, request):
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
    id_factory = DeterministicIdFactory(
        scenario_id="test", scenario_version=1, seed=seed
    )
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
    executor = ToolExecutor(registry, FaultEngine(()))
    provider = _EchoProvider()
    context = _make_context()
    from flight_agent_evaluator.contracts.aviation import FlightIdentity, FlightStatusQuery
    from flight_agent_evaluator.contracts.common import NonEmptyIdentifier
    from datetime import date

    query = FlightStatusQuery(
        query_id=NonEmptyIdentifier(value="q-1"),
        flight_identity=FlightIdentity(flight_number="AS142", marketing_airline_iata="AS"),
        query_date=date(2026, 7, 28),
    )
    call = ToolCall(
        call_id=uuid.uuid4(),
        tool_name="echo",
        arguments={"query": query},
    )
    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(call, provider=provider, context=context, journal=None)
    )
    assert result.status == "success"
    assert result.result == {"flight_id": "AS142"}


def test_executor_returns_failure_for_unknown_tool():
    registry = ToolRegistry()
    executor = ToolExecutor(registry, FaultEngine(()))
    context = _make_context()
    call = ToolCall(
        call_id=uuid.uuid4(),
        tool_name="not.registered",
        arguments={},
    )
    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(call, provider=None, context=context, journal=None)
    )
    assert result.status == "failure"
    assert result.error.error_type == "invalid_arguments"


def test_executor_handles_handler_exception():
    class _BrokenHandler:
        tool_name = "broken"

        def __init__(self):
            self.tool_definition = ToolDefinition(
                name=self.tool_name, description="broken"
            )

        async def execute(self, arguments, provider, context):
            raise RuntimeError("boom")

    registry = ToolRegistry()
    registry.register(_BrokenHandler())
    executor = ToolExecutor(registry, FaultEngine(()))
    context = _make_context()
    call = ToolCall(
        call_id=uuid.uuid4(),
        tool_name="broken",
        arguments={},
    )
    result = asyncio.get_event_loop().run_until_complete(
        executor.execute(call, provider=None, context=context, journal=None)
    )
    assert result.status == "failure"
    assert result.error.error_type == "internal_error"
    assert "boom" in result.error.message
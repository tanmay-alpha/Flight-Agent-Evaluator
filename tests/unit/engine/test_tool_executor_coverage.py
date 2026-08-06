"""Additional unit tests for ToolExecutor branch coverage."""

from __future__ import annotations

import asyncio
import datetime
import uuid

from flight_agent_evaluator.contracts.faults import (
    ActivationRule,
    DelayedResponseFault,
    DuplicateEventFault,
)
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.tools.base import ToolDefinition, ToolRegistry


class DummyProvider:
    pass


def _make_context(clock=None):
    if clock is None:
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
        correlation_id="corr-1",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


def test_tool_executor_limit_exceeded():
    registry = ToolRegistry()
    executor = ToolExecutor(registry=registry, tool_call_limit=1)
    context = _make_context()

    tc1 = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="unknown_tool",
        arguments={},
        mutation_class="read_only",
        start_time=context.clock.now(),
    )

    res1 = asyncio.run(executor.execute(tc1, context=context))
    assert res1.status == "failure"
    assert executor.call_count == 1

    res2 = asyncio.run(executor.execute(tc1, context=context))
    assert res2.status == "failure"
    assert res2.error is not None
    assert res2.error.message.startswith("Tool-call limit exceeded")
    assert executor.call_count == 2


def test_tool_executor_time_limit_exceeded():
    registry = ToolRegistry()

    class KnownTool:
        tool_name = "some_tool"
        tool_definition = ToolDefinition(
            name="some_tool", description="d", mutation_class="read_only", input_schema={}
        )

        async def execute(self, arguments, provider, context):
            return {}

    registry.register(KnownTool())
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    executor = ToolExecutor(registry=registry, clock=clock, logical_time_limit_ns=100)
    context = _make_context(clock)

    clock.advance(3600)

    tc = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="some_tool",
        arguments={},
        mutation_class="read_only",
        start_time=clock.now(),
    )

    res = asyncio.run(executor.execute(tc, context=context))
    assert res.status == "timeout"
    assert res.error is not None
    assert "Logical time limit exceeded" in res.error.message


def test_tool_executor_invalid_arguments_schema():
    registry = ToolRegistry()

    class TestTool:
        tool_name = "test_tool"
        tool_definition = ToolDefinition(
            name="test_tool",
            description="test",
            mutation_class="read_only",
            input_schema={
                "type": "object",
                "required": ["flight_id", "count"],
                "properties": {
                    "flight_id": {"type": "string", "minLength": 3, "maxLength": 10},
                    "count": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "additionalProperties": False,
            },
        )

        async def execute(self, arguments, provider, context):
            return {"status": "ok"}

    registry.register(TestTool())
    executor = ToolExecutor(registry=registry, provider=DummyProvider())  # type: ignore[arg-type]
    context = _make_context()

    tc_missing = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="test_tool",
        arguments={"flight_id": "AA100"},
        mutation_class="read_only",
        start_time=context.clock.now(),
    )
    res_missing = asyncio.run(executor.execute(tc_missing, context=context))
    assert res_missing.status == "failure"
    assert res_missing.error is not None
    assert "input schema" in res_missing.error.message

    tc_extra = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="test_tool",
        arguments={"flight_id": "AA100", "count": 2, "extra": "bad"},
        mutation_class="read_only",
        start_time=context.clock.now(),
    )
    res_extra = asyncio.run(executor.execute(tc_extra, context=context))
    assert res_extra.status == "failure"

    tc_range = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="test_tool",
        arguments={"flight_id": "AA", "count": 0},
        mutation_class="read_only",
        start_time=context.clock.now(),
    )
    res_range = asyncio.run(executor.execute(tc_range, context=context))
    assert res_range.status == "failure"


def test_tool_executor_handler_exceptions():
    registry = ToolRegistry()

    class ValueErrorTool:
        tool_name = "val_err"
        tool_definition = ToolDefinition(
            name="val_err", description="d", mutation_class="read_only", input_schema={}
        )

        async def execute(self, arguments, provider, context):
            raise ValueError("Validation failed inside handler")

    class UnexpectedErrorTool:
        tool_name = "unexp_err"
        tool_definition = ToolDefinition(
            name="unexp_err", description="d", mutation_class="read_only", input_schema={}
        )

        async def execute(self, arguments, provider, context):
            raise RuntimeError("Unexpected error")

    registry.register(ValueErrorTool())
    registry.register(UnexpectedErrorTool())

    executor = ToolExecutor(registry=registry, provider=DummyProvider())  # type: ignore[arg-type]
    context = _make_context()

    tc_val = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="val_err",
        arguments={},
        mutation_class="read_only",
        start_time=context.clock.now(),
    )
    res_val = asyncio.run(executor.execute(tc_val, context=context))
    assert res_val.status == "failure"
    assert res_val.error is not None
    assert res_val.error.error_type == "invalid_arguments"

    tc_unexp = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="unexp_err",
        arguments={},
        mutation_class="read_only",
        start_time=context.clock.now(),
    )
    res_unexp = asyncio.run(executor.execute(tc_unexp, context=context))
    assert res_unexp.status == "failure"
    assert res_unexp.error is not None
    assert res_unexp.error.error_type == "internal_error"


def test_tool_executor_fault_execution():
    registry = ToolRegistry()

    class OkTool:
        tool_name = "ok_tool"
        tool_definition = ToolDefinition(
            name="ok_tool", description="d", mutation_class="read_only", input_schema={}
        )

        async def execute(self, arguments, provider, context):
            return {"status": "ok"}

    registry.register(OkTool())
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    journal = HashChainJournal()

    fault_delay = DelayedResponseFault(
        target_provider="synthetic-fixture",
        target_tool="ok_tool",
        activation=ActivationRule(kind="always"),
        occurrence_count=1,
        delay_seconds=10,
    )
    fault_dup = DuplicateEventFault(
        target_provider="synthetic-fixture",
        target_tool="ok_tool",
        activation=ActivationRule(kind="always"),
        occurrence_count=1,
        duplication_count=2,
    )

    executor = ToolExecutor(
        registry=registry,
        faults=(fault_delay, fault_dup),
        clock=clock,
        journal=journal,
        provider=DummyProvider(),  # type: ignore[arg-type]
        logical_time_limit_ns=2_000_000_000_000_000_000,
    )
    context = _make_context(clock)

    tc = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="ok_tool",
        arguments={},
        mutation_class="read_only",
        start_time=clock.now(),
    )

    t0 = clock.now()
    res1 = asyncio.run(executor.execute(tc, context=context))
    assert res1.status == "success"
    assert (clock.now() - t0).total_seconds() == 10

    res2 = asyncio.run(executor.execute(tc, context=context))
    assert res2.status == "success"
    dup_events = [e for e in journal.entries if e.type == "domain_event"]
    assert len(dup_events) == 2

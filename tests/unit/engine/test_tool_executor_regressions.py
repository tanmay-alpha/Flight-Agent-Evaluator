"""Executor boundaries must preserve complete, bounded evidence."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest
from tests.unit.agent.test_agent_loop import _make_context

from flight_agent_evaluator.contracts.faults import ActivationRule, TimeoutFault
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.environment.errors import AmbiguousCommitError
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.tools.base import ToolDefinition, ToolRegistry


class Handler:
    tool_name = "mutation"
    tool_definition = ToolDefinition(
        name="mutation",
        description="test",
        mutation_class="simulated_mutation",
        input_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "number", "minimum": 0}},
        },
    )

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.invocations = 0

    async def execute(
        self, arguments: dict[str, Any], provider: Any, context: Any
    ) -> dict[str, Any]:
        self.invocations += 1
        if self.error is not None:
            raise self.error
        return {"ok": True}


def execute_case(
    handler: Handler, arguments: dict[str, Any], *, faults: tuple[TimeoutFault, ...] = ()
) -> tuple[ToolExecutor, HashChainJournal, ToolCall]:
    context = _make_context()
    registry = ToolRegistry()
    registry.register(handler)
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry,
        faults=faults,
        journal=journal,
        provider=FixtureFlightProvider(),
        execution_policy=ExecutionToolPolicy(
            scenario_id=context.scenario_id,
            allowed_tool_names=("mutation",),
            allowed_mutation_classes=("simulated_mutation",),
            maximum_mutations=1,
        ),
    )
    call = ToolCall(
        call_id=uuid.UUID(int=1),
        run_id=context.run_id,
        tool_name="mutation",
        arguments=arguments,
        start_time=context.clock.now(),
    )
    return executor, journal, call


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_arguments_are_rejected(value: float) -> None:
    handler = Handler()
    executor, journal, call = execute_case(handler, {"value": value})
    result = asyncio.run(executor.execute(call, context=_make_context()))
    assert result.error is not None and result.error.error_type == "invalid_arguments"
    assert handler.invocations == 0
    assert journal.verify()


def test_invalid_arguments_do_not_trigger_faults() -> None:
    fault = TimeoutFault(
        target_provider="fixture",
        target_tool="mutation",
        activation=ActivationRule(kind="always"),
        occurrence_count=1,
        timeout_seconds=1,
    )
    executor, journal, call = execute_case(Handler(), {}, faults=(fault,))
    result = asyncio.run(executor.execute(call, context=_make_context()))
    assert result.error is not None and result.error.error_type == "invalid_arguments"
    assert [entry.type for entry in journal.entries] == ["tool_call", "tool_result"]
    valid = call.model_copy(update={"arguments": {"value": 1}})
    faulted = asyncio.run(executor.execute(valid, context=_make_context()))
    assert faulted.status == "timeout"
    denied = asyncio.run(executor.execute(valid, context=_make_context()))
    assert denied.error is not None and denied.error.error_type == "authorization_error"


@pytest.mark.parametrize(
    "error", [AmbiguousCommitError("lost"), RuntimeError("lost"), ValueError("lost")]
)
def test_unknown_mutation_outcome_consumes_mutation_budget(error: Exception) -> None:
    handler = Handler(error)
    executor, journal, call = execute_case(handler, {"value": 1})
    asyncio.run(executor.execute(call, context=_make_context()))
    result = asyncio.run(
        executor.execute(
            call.model_copy(update={"call_id": uuid.UUID(int=2)}), context=_make_context()
        )
    )
    assert result.error is not None and result.error.error_type == "authorization_error"
    assert handler.invocations == 1
    assert journal.entry_count == 4


def test_cancellation_journals_unknown_mutation_outcome_before_reraising() -> None:
    executor, journal, call = execute_case(Handler(asyncio.CancelledError()), {"value": 1})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(executor.execute(call, context=_make_context()))
    assert [entry.type for entry in journal.entries] == ["tool_call", "tool_result"]
    assert journal.entries[-1].payload["error"]["error_type"] == "cancelled"
    assert journal.entries[-1].payload["error"]["details"]["outcome"] == "unknown"


def test_oversized_arguments_are_replaced_with_digest() -> None:
    handler = Handler()
    executor, journal, call = execute_case(handler, {"value": 1, "large": "x" * 65536})
    result = asyncio.run(executor.execute(call, context=_make_context()))
    assert result.error is not None and result.error.error_type == "invalid_arguments"
    payload = journal.entries[0].payload
    assert "arguments" not in payload
    assert len(payload["arguments_digest"]) == 64
    assert handler.invocations == 0


def test_journal_lone_surrogate_round_trip(tmp_path: Path) -> None:
    executor, journal, call = execute_case(Handler(), {"value": 1, "text": "\ud800"})
    asyncio.run(executor.execute(call, context=_make_context()))
    path = tmp_path / "journal.jsonl"
    journal.write_jsonl(path)
    loaded = HashChainJournal.read_verified_jsonl(path)
    assert loaded.final_digest() == journal.final_digest()
    assert loaded.entries[0].payload["arguments"]["text"] == "\ud800"


@pytest.mark.parametrize("text", ['{"seq":1,"seq":2}', '{"payload":{"x":NaN}}'])
def test_journal_reader_rejects_non_strict_json(tmp_path: Path, text: str) -> None:
    from flight_agent_evaluator.strict_json import StrictJSONError

    path = tmp_path / "journal.jsonl"
    path.write_text(text + "\n", encoding="utf-8")
    with pytest.raises(StrictJSONError):
        HashChainJournal.read_unverified_jsonl(path)

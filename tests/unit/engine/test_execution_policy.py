"""Layer 1 regression tests for executor-owned authorization metadata."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.tools.base import build_transactional_registry


class _Provider:
    """A provider is unused by the transactional handlers under test."""


def _context() -> RunContext:
    clock = DeterministicVirtualClock(datetime(2026, 8, 12, 12, tzinfo=UTC))
    return RunContext(
        run_id=uuid.uuid4(),
        scenario_id="layer-1-security",
        scenario_version=1,
        seed=7,
        clock=clock,
        id_factory=DeterministicIdFactory("layer-1-security", 1, 7),
        tool_call_limit=10,
        time_limit_seconds=60,
        correlation_id="layer-1",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


def _call(
    context: RunContext, tool_name: str, arguments: dict[str, Any], mutation_class: str
) -> ToolCall:
    return ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name=tool_name,
        arguments=arguments,
        mutation_class=mutation_class,  # deliberately untrusted input
        start_time=context.clock.now(),
    )


def test_hidden_registered_mutation_is_denied_and_journaled() -> None:
    env = SimulatedAirlineEnvironment()
    context = _context()
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry=build_transactional_registry(env),
        provider=_Provider(),  # type: ignore[arg-type]
        journal=journal,
        execution_policy=ExecutionToolPolicy(
            scenario_id=context.scenario_id,
            allowed_tool_names=("booking.get_current",),
            allowed_mutation_classes=("read_only",),
        ),
    )

    result = asyncio.run(
        executor.execute(
            _call(
                context,
                "notification.send_simulated",
                {"passenger_name": "Jane Doe", "message": "unsafe", "idempotency_key": "notify-1"},
                "read_only",
            ),
            context=context,
        )
    )

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.error_type == "authorization_error"
    assert env.notifications == []
    assert journal.entries[0].payload["authorization_decision"] == "denied"
    assert journal.entries[0].payload["mutation_class"] == "simulated_mutation"


def test_executor_fails_closed_without_a_scenario_policy() -> None:
    env = SimulatedAirlineEnvironment()
    context = _context()
    executor = ToolExecutor(
        registry=build_transactional_registry(env),
        provider=_Provider(),  # type: ignore[arg-type]
    )

    result = asyncio.run(
        executor.execute(
            _call(
                context,
                "notification.send_simulated",
                {"passenger_name": "Jane Doe", "message": "unsafe", "idempotency_key": "no-policy"},
                "simulated_mutation",
            ),
            context=context,
        )
    )

    assert result.error is not None
    assert result.error.error_type == "authorization_error"
    assert env.notifications == []


def test_forged_mutation_class_is_rejected_before_handler_execution() -> None:
    env = SimulatedAirlineEnvironment()
    context = _context()
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry=build_transactional_registry(env),
        provider=_Provider(),  # type: ignore[arg-type]
        journal=journal,
        execution_policy=ExecutionToolPolicy(
            scenario_id=context.scenario_id,
            allowed_tool_names=("notification.send_simulated",),
            allowed_mutation_classes=("simulated_mutation",),
        ),
    )

    result = asyncio.run(
        executor.execute(
            _call(
                context,
                "notification.send_simulated",
                {"passenger_name": "Jane Doe", "message": "unsafe", "idempotency_key": "notify-2"},
                "read_only",
            ),
            context=context,
        )
    )

    assert result.status == "failure"
    assert result.error is not None
    assert result.error.error_type == "authorization_error"
    assert env.notifications == []
    assert journal.entries[0].payload["mutation_class"] == "simulated_mutation"
    assert journal.entries[0].payload["requested_mutation_class"] == "read_only"


def test_forged_read_only_cannot_downgrade_sensitive_confirmation() -> None:
    """The sensitive registry classification wins before its handler can run."""
    env = SimulatedAirlineEnvironment()
    context = _context()
    hold = env.place_hold(
        booking_reference="AS-1001",
        offer_id="offer-alt-1",
        flight_number="AS144",
        origin="JFK",
        destination="LHR",
        price_amount=550.0,
        idempotency_key="hold-for-forged-confirm",
        current_time=context.clock.now(),
    )
    approval = env.request_approval(
        booking_reference="AS-1001",
        action_type="confirm_rebooking",
        offer_id="offer-alt-1",
        hold_id=hold["hold_id"],
        reason="Approved by the trusted environment.",
        idempotency_key="approval-for-forged-confirm",
        current_time=context.clock.now(),
    )
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry=build_transactional_registry(env),
        provider=_Provider(),  # type: ignore[arg-type]
        journal=journal,
        execution_policy=ExecutionToolPolicy(
            scenario_id=context.scenario_id,
            allowed_tool_names=("booking.confirm_rebooking",),
            allowed_mutation_classes=("read_only", "sensitive_simulated_mutation"),
            maximum_mutations=1,
            allow_sensitive_mutations=True,
        ),
    )

    result = asyncio.run(
        executor.execute(
            _call(
                context,
                "booking.confirm_rebooking",
                {
                    "booking_reference": "AS-1001",
                    "hold_id": hold["hold_id"],
                    "approval_id": approval["approval_id"],
                    "idempotency_key": "forged-sensitive-confirm",
                },
                "read_only",
            ),
            context=context,
        )
    )

    assert result.error is not None
    assert result.error.error_type == "authorization_error"
    assert env.transactions == []
    assert env.holds[hold["hold_id"]].status.value == "active"
    assert journal.entries[0].payload["mutation_class"] == "sensitive_simulated_mutation"

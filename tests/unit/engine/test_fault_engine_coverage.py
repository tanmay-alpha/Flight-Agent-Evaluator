"""Branch coverage tests for FaultEngine activation rules and exception handling."""

from __future__ import annotations

import datetime
import uuid

import pytest

from flight_agent_evaluator.contracts.faults import ActivationRule, TimeoutFault
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.fault_engine import (
    FaultEngine,
    UnsupportedFaultConfigurationError,
)


def _make_tool_call(tool_name: str = "search", arguments=None):
    return ToolCall(
        call_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        tool_name=tool_name,
        arguments=arguments or {},
        mutation_class="read_only",
        start_time=datetime.datetime.now(datetime.UTC),
    )


def test_after_n_calls_missing_call_index_raises():
    fault = TimeoutFault(
        target_provider="p",
        target_tool="t",
        activation=ActivationRule(kind="after_n_calls", call_index=None),
        occurrence_count=1,
        timeout_seconds=1,
    )
    engine = FaultEngine((fault,))
    call = _make_tool_call("t")
    with pytest.raises(UnsupportedFaultConfigurationError, match="call_index"):
        engine.apply(call, sequence=0)


def test_on_match_activation_missing_substring_raises():
    fault = TimeoutFault(
        target_provider="p",
        target_tool="t",
        activation=ActivationRule(kind="on_match", match_substring=None),
        occurrence_count=1,
        timeout_seconds=1,
    )
    engine = FaultEngine((fault,))
    call = _make_tool_call("t")
    with pytest.raises(UnsupportedFaultConfigurationError, match="match_substring"):
        engine.apply(call, sequence=0)


def test_time_window_missing_bounds_or_clock_raises():
    fault = TimeoutFault(
        target_provider="p",
        target_tool="t",
        activation=ActivationRule(kind="time_window", window_start=None, window_end=None),
        occurrence_count=1,
        timeout_seconds=1,
    )
    engine = FaultEngine((fault,))
    call = _make_tool_call("t")
    with pytest.raises(UnsupportedFaultConfigurationError, match="window_start"):
        engine.apply(call, sequence=0)

    # Missing clock with valid bounds
    dt1 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    dt2 = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    fault_valid_bounds = TimeoutFault(
        target_provider="p",
        target_tool="t",
        activation=ActivationRule(kind="time_window", window_start=dt1, window_end=dt2),
        occurrence_count=1,
        timeout_seconds=1,
    )
    engine_no_clock = FaultEngine((fault_valid_bounds,), clock=None)
    with pytest.raises(UnsupportedFaultConfigurationError, match="deterministic clock"):
        engine_no_clock.apply(call, sequence=0)


def test_unsupported_activation_kind_raises():
    rule = ActivationRule.model_construct(kind="unknown_kind")  # type: ignore[arg-type]
    fault = TimeoutFault(
        target_provider="p",
        target_tool="t",
        activation=rule,
        occurrence_count=1,
        timeout_seconds=1,
    )
    engine = FaultEngine((fault,))
    call = _make_tool_call("t")
    with pytest.raises(UnsupportedFaultConfigurationError, match="Unsupported activation kind"):
        engine.apply(call, sequence=0)

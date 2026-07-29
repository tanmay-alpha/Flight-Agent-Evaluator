"""Tests for runtime.primitives."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from flight_agent_evaluator.runtime.clock import (
    DeterministicVirtualClock,
    VirtualClock,
)
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot


# ---------------------------------------------------------------------------
# VirtualClock
# ---------------------------------------------------------------------------


class TestVirtualClock:
    """VirtualClock must be deterministic, UTC-only, and never read the wall clock."""

    def test_now_returns_initial_time(self):
        ref = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        clock = DeterministicVirtualClock(start=ref)
        assert clock.now() == ref

    def test_advance_moves_clock_forward(self):
        ref = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        clock = DeterministicVirtualClock(start=ref)
        result = clock.advance(seconds=30)
        expected = ref + timedelta(seconds=30)
        assert result == expected
        assert clock.now() == expected

    def test_advance_zero_returns_same_time(self):
        ref = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        clock = DeterministicVirtualClock(start=ref)
        result = clock.advance(seconds=0)
        assert result == ref

    def test_advance_negative_raises(self):
        ref = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        clock = DeterministicVirtualClock(start=ref)
        with pytest.raises(ValueError, match="negative"):
            clock.advance(seconds=-1)

    def test_multiple_advances_accumulate(self):
        ref = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        clock = DeterministicVirtualClock(start=ref)
        clock.advance(seconds=10)
        clock.advance(seconds=20)
        assert clock.now() == ref + timedelta(seconds=30)

    def test_returns_timezone_aware_utc(self):
        ref = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        clock = DeterministicVirtualClock(start=ref)
        result = clock.now()
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)

    def test_isolated_per_run(self):
        """Two independent clocks with the same start must not share state."""
        ref = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        clock_a = DeterministicVirtualClock(start=ref)
        clock_b = DeterministicVirtualClock(start=ref)
        clock_a.advance(seconds=5)
        assert clock_b.now() == ref  # b must be unaffected


# ---------------------------------------------------------------------------
# DeterministicIdFactory
# ---------------------------------------------------------------------------


class TestDeterministicIdFactory:
    """IDs must be deterministic: same inputs → same UUIDs across runs."""

    def test_same_inputs_same_uuid(self):
        factory = DeterministicIdFactory(
            scenario_id="SCN-001",
            scenario_version=1,
            seed=42,
        )
        id_a = factory.next(record_type="tool_call", sequence=1)
        id_b = factory.next(record_type="tool_call", sequence=1)
        assert id_a == id_b

    def test_different_seed_different_uuid(self):
        factory_a = DeterministicIdFactory(
            scenario_id="SCN-001", scenario_version=1, seed=42
        )
        factory_b = DeterministicIdFactory(
            scenario_id="SCN-001", scenario_version=1, seed=99
        )
        id_a = factory_a.next(record_type="tool_call", sequence=1)
        id_b = factory_b.next(record_type="tool_call", sequence=1)
        assert id_a != id_b

    def test_different_sequence_different_uuid(self):
        factory = DeterministicIdFactory(
            scenario_id="SCN-001", scenario_version=1, seed=42
        )
        id_1 = factory.next(record_type="tool_call", sequence=1)
        id_2 = factory.next(record_type="tool_call", sequence=2)
        assert id_1 != id_2

    def test_different_record_type_different_uuid(self):
        factory = DeterministicIdFactory(
            scenario_id="SCN-001", scenario_version=1, seed=42
        )
        id_a = factory.next(record_type="tool_call", sequence=1)
        id_b = factory.next(record_type="tool_result", sequence=1)
        assert id_a != id_b

    def test_uuid_version_is_5(self):
        factory = DeterministicIdFactory(
            scenario_id="SCN-001", scenario_version=1, seed=42
        )
        id_ = factory.next(record_type="tool_call", sequence=1)
        assert id_.version == 5

    def test_no_uuid4_in_runtime(self):
        """The runtime must never produce UUIDv4 identifiers."""
        factory = DeterministicIdFactory(
            scenario_id="SCN-001", scenario_version=1, seed=42
        )
        for seq in range(10):
            id_ = factory.next(record_type="tool_call", sequence=seq)
            assert id_.version != 4

    def test_cross_process_stability(self):
        """Same inputs produce identical UUIDs (simulated by re-instantiation)."""
        params = dict(scenario_id="SCN-001", scenario_version=1, seed=42)
        factory_a = DeterministicIdFactory(**params)
        factory_b = DeterministicIdFactory(**params)
        for seq in range(20):
            assert factory_a.next("tool_call", seq) == factory_b.next(
                "tool_call", seq
            )


# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------


class TestRunContext:
    def test_immutable_after_construction(self):
        clock = DeterministicVirtualClock(
            start=datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
        )
        factory = DeterministicIdFactory(
            scenario_id="SCN-001", scenario_version=1, seed=42
        )
        ctx = RunContext(
            run_id=factory.next("run", 1),
            scenario_id="SCN-001",
            scenario_version=1,
            seed=42,
            clock=clock,
            id_factory=factory,
            tool_call_limit=10,
            time_limit_seconds=300,
            correlation_id="CORR-001",
            scenario_digest="a" * 64,
            trajectory_digest="b" * 64,
        )
        with pytest.raises((AttributeError, TypeError)):
            ctx.run_id = uuid.uuid4()


# ---------------------------------------------------------------------------
# StateSnapshot
# ---------------------------------------------------------------------------


class TestStateSnapshot:
    def test_valid_state_accepted(self):
        snap = StateSnapshot.model_validate(
            {"data": {"flights": 3, "cancelled": False}}
        )
        assert snap.data["flights"] == 3

    def test_non_json_value_rejected(self):
        with pytest.raises(Exception):  # Pydantic validation error
            StateSnapshot.model_validate(
                {"data": {"value": datetime.now(UTC)}}
            )

    def test_nested_dict_validated(self):
        snap = StateSnapshot.model_validate(
            {"data": {"nested": {"count": 1, "items": [1, 2, 3]}}}
        )
        assert snap.data["nested"]["count"] == 1

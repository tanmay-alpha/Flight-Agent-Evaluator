"""Unit tests for TrajectoryReferenceResolver."""

from __future__ import annotations

import pytest

from flight_agent_evaluator.drivers.resolver import (
    PriorStepRecord,
    TrajectoryReferenceError,
    TrajectoryReferenceResolver,
)


def test_resolver_basic_structured_ref() -> None:
    resolver = TrajectoryReferenceResolver()
    prior = [
        PriorStepRecord(
            step_index=0,
            tool_name="booking.hold_seats",
            success=True,
            result={"hold_id": "HOLD-9999", "status": "active"},
        )
    ]
    args = {"hold_id": {"$ref_step": 0, "json_pointer": "/hold_id"}, "reason": "delay"}
    resolved = resolver.resolve_arguments(args, prior)
    assert resolved == {"hold_id": "HOLD-9999", "reason": "delay"}


def test_resolver_string_ref_format() -> None:
    resolver = TrajectoryReferenceResolver()
    prior = [
        PriorStepRecord(
            step_index=0,
            tool_name="approval.request",
            success=True,
            result={"approval_id": "APP-1234", "decision": "APPROVED"},
        )
    ]
    args = {"approval_id": "$ref:0/approval_id", "confirm": True}
    resolved = resolver.resolve_arguments(args, prior)
    assert resolved == {"approval_id": "APP-1234", "confirm": True}


def test_resolver_cross_step_hold_to_approval_to_rebooking() -> None:
    resolver = TrajectoryReferenceResolver()
    prior = [
        PriorStepRecord(
            step_index=0,
            tool_name="booking.hold_seats",
            success=True,
            result={"hold_id": "HOLD-777", "expires_at": "2026-08-14T10:00:00Z"},
        ),
        PriorStepRecord(
            step_index=1,
            tool_name="approval.request",
            success=True,
            result={"approval_id": "APP-888", "hold_id": "HOLD-777"},
        ),
    ]

    # Step 1 input referenced Step 0 hold_id
    args1 = {"hold_id": "$ref:0/hold_id", "sensitive": True}
    res1 = resolver.resolve_arguments(args1, prior[:1])
    assert res1["hold_id"] == "HOLD-777"

    # Step 2 input references Step 1 approval_id
    args2 = {"approval_id": "$ref:1/approval_id", "hold_id": "$ref:0/hold_id"}
    res2 = resolver.resolve_arguments(args2, prior)
    assert res2 == {"approval_id": "APP-888", "hold_id": "HOLD-777"}


def test_resolver_missing_pointer_raises() -> None:
    resolver = TrajectoryReferenceResolver()
    prior = [
        PriorStepRecord(
            step_index=0,
            tool_name="flight.search",
            success=True,
            result={"flights": []},
        )
    ]
    args = {"id": {"$ref_step": 0, "json_pointer": "/missing_key"}}
    with pytest.raises(TrajectoryReferenceError, match="not found"):
        resolver.resolve_arguments(args, prior)


def test_resolver_failed_prior_step_raises() -> None:
    resolver = TrajectoryReferenceResolver()
    prior = [
        PriorStepRecord(
            step_index=0,
            tool_name="booking.hold_seats",
            success=False,
            result={"error": "seat unavailable"},
        )
    ]
    args = {"hold_id": "$ref:0/hold_id"}
    with pytest.raises(TrajectoryReferenceError, match="Cannot reference failed step"):
        resolver.resolve_arguments(args, prior)


def test_resolver_out_of_range_index_raises() -> None:
    resolver = TrajectoryReferenceResolver()
    prior = [
        PriorStepRecord(
            step_index=0,
            tool_name="flight.search",
            success=True,
            result={"status": "ok"},
        )
    ]
    args = {"ref": "$ref:5/status"}
    with pytest.raises(TrajectoryReferenceError, match="out of range"):
        resolver.resolve_arguments(args, prior)

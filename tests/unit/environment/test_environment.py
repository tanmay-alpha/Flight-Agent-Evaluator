"""Unit tests for the simulated transactional airline environment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from flight_agent_evaluator.environment.contracts import (
    BookingStatus,
    HoldStatus,
)
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.environment.errors import (
    ApprovalExpiredError,
    ApprovalMissingError,
    IdempotencyConflictError,
    StateTransitionError,
)
from flight_agent_evaluator.environment.fixtures import get_default_approval_fixture
from flight_agent_evaluator.environment.state import (
    validate_booking_transition,
    validate_hold_transition,
)


def test_booking_and_hold_state_transitions() -> None:
    # Valid transitions
    validate_booking_transition(BookingStatus.DISRUPTED, BookingStatus.HOLD_PLACED)
    validate_booking_transition(BookingStatus.HOLD_PLACED, BookingStatus.REBOOKED)

    # Invalid transitions
    with pytest.raises(StateTransitionError):
        validate_booking_transition(BookingStatus.UNBOOKED, BookingStatus.REBOOKED)

    validate_hold_transition(HoldStatus.ACTIVE, HoldStatus.CONFIRMED)
    with pytest.raises(StateTransitionError):
        validate_hold_transition(HoldStatus.CONFIRMED, HoldStatus.RELEASED)


def test_simulated_environment_place_hold_and_release() -> None:
    env = SimulatedAirlineEnvironment()
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)

    # Place hold
    res = env.place_hold(
        booking_reference="AS-1001",
        offer_id="offer-alt-1",
        flight_number="AS144",
        origin="JFK",
        destination="LHR",
        price_amount=550.0,
        idempotency_key="key-hold-001",
        current_time=now,
    )
    assert res["status"] == "placed"
    hold_id = res["hold_id"]

    # Check booking status updated
    booking = env.get_booking("AS-1001")
    assert booking.status == BookingStatus.HOLD_PLACED
    assert booking.active_hold_id == hold_id

    # Test idempotency (same key returns cached result)
    res_retry = env.place_hold(
        booking_reference="AS-1001",
        offer_id="offer-alt-1",
        flight_number="AS144",
        origin="JFK",
        destination="LHR",
        price_amount=550.0,
        idempotency_key="key-hold-001",
        current_time=now,
    )
    assert res_retry["hold_id"] == hold_id

    # Test idempotency conflict (same key, different payload)
    with pytest.raises(IdempotencyConflictError):
        env.place_hold(
            booking_reference="AS-1001",
            offer_id="offer-DIFFERENT",
            flight_number="AS144",
            origin="JFK",
            destination="LHR",
            price_amount=550.0,
            idempotency_key="key-hold-001",
            current_time=now,
        )

    # Release hold
    rel = env.release_hold(hold_id=hold_id, idempotency_key="key-rel-001", current_time=now)
    assert rel["status"] == "released"
    assert env.holds[hold_id].status == HoldStatus.RELEASED


def test_confirm_rebooking_with_approval() -> None:
    env = SimulatedAirlineEnvironment()
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)

    # 1. Place hold first to transition booking status to HOLD_PLACED
    hold_res = env.place_hold(
        booking_reference="AS-1001",
        offer_id="offer-alt-1",
        flight_number="AS144",
        origin="JFK",
        destination="LHR",
        price_amount=550.0,
        idempotency_key="key-hold-001",
        current_time=now,
    )
    hold_id = hold_res["hold_id"]

    # Register matching approval
    appr = get_default_approval_fixture(
        booking_reference="AS-1001",
        mutation_payload={"booking_reference": "AS-1001", "hold_id": hold_id},
    )
    env.approvals.register_request(appr)

    # 2. Confirm rebooking
    res = env.confirm_rebooking(
        booking_reference="AS-1001",
        hold_id=hold_id,
        approval_id=appr.approval_id,
        idempotency_key="key-confirm-001",
        current_time=now,
    )
    assert res["status"] == "confirmed"
    assert res["rebooked_flight_number"] == "AS144"

    booking = env.get_booking("AS-1001")
    assert booking.status == BookingStatus.REBOOKED
    assert booking.rebooked_flight_number == "AS144"


def test_confirm_rebooking_missing_or_expired_approval() -> None:
    env = SimulatedAirlineEnvironment()
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)

    hold_res = env.place_hold(
        booking_reference="AS-1001",
        offer_id="offer-alt-1",
        flight_number="AS144",
        origin="JFK",
        destination="LHR",
        price_amount=550.0,
        idempotency_key="key-hold-001",
        current_time=now,
    )
    hold_id = hold_res["hold_id"]

    # Missing approval ID
    with pytest.raises(ApprovalMissingError):
        env.confirm_rebooking(
            booking_reference="AS-1001",
            hold_id=hold_id,
            approval_id="",
            idempotency_key="key-err-1",
            current_time=now,
        )

    # Expired approval ID (set current_time 2 hours later)
    appr = get_default_approval_fixture(
        booking_reference="AS-1001",
        mutation_payload={"booking_reference": "AS-1001", "hold_id": hold_id},
    )
    env.approvals.register_request(appr)
    future = now + timedelta(hours=2)
    with pytest.raises(ApprovalExpiredError):
        env.confirm_rebooking(
            booking_reference="AS-1001",
            hold_id=hold_id,
            approval_id=appr.approval_id,
            idempotency_key="key-err-2",
            current_time=future,
        )

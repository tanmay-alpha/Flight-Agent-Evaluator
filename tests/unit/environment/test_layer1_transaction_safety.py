"""Adversarial Layer 1 transaction-boundary regression tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest

from flight_agent_evaluator.environment.contracts import BookingStatus
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.environment.errors import (
    IdempotencyConflictError,
    OwnershipMismatchError,
    StateTransitionError,
    UnknownOfferError,
)

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)


def _hold(
    env: SimulatedAirlineEnvironment, booking_reference: str = "AS-1001", key: str | None = None
) -> str:
    return str(
        env.place_hold(
            booking_reference=booking_reference,
            offer_id="offer-alt-1",
            flight_number="AS144",
            origin="JFK",
            destination="LHR",
            price_amount=550.0,
            idempotency_key=key or f"hold-{booking_reference}",
            current_time=NOW,
        )["hold_id"]
    )


def _approval(
    env: SimulatedAirlineEnvironment, hold_id: str, booking_reference: str = "AS-1001"
) -> str:
    return str(
        env.request_approval(
            booking_reference=booking_reference,
            action_type="confirm_rebooking",
            offer_id="offer-alt-1",
            hold_id=hold_id,
            reason="Disruption remediation.",
            idempotency_key=f"approval-{booking_reference}",
            current_time=NOW,
        )["approval_id"]
    )


def test_foreign_hold_cannot_be_approved_or_confirmed_without_state_change() -> None:
    env = SimulatedAirlineEnvironment()
    booking_b = env.get_booking("AS-1001").model_copy(
        update={"booking_reference": "AS-2002", "passenger_name": "Passenger B"}
    )
    env.bookings["AS-2002"] = booking_b
    hold_b = _hold(env, "AS-2002")

    with pytest.raises(OwnershipMismatchError):
        env.request_approval(
            booking_reference="AS-1001",
            action_type="confirm_rebooking",
            offer_id="offer-alt-1",
            hold_id=hold_b,
            reason="forged relationship",
            idempotency_key="foreign-approval",
            current_time=NOW,
        )

    approval_b = _approval(env, hold_b, "AS-2002")
    before = (env.get_booking("AS-1001"), env.get_booking("AS-2002"), env.holds[hold_b])
    with pytest.raises(OwnershipMismatchError):
        env.confirm_rebooking(
            booking_reference="AS-1001",
            hold_id=hold_b,
            approval_id=approval_b,
            idempotency_key="foreign-confirm",
            current_time=NOW,
        )

    assert (env.get_booking("AS-1001"), env.get_booking("AS-2002"), env.holds[hold_b]) == before
    assert env.transactions == []
    assert env.notifications == []


def test_invented_offer_and_invalid_transition_leave_no_orphan_hold() -> None:
    env = SimulatedAirlineEnvironment()
    before_holds = dict(env.holds)
    with pytest.raises(UnknownOfferError):
        env.place_hold(
            booking_reference="AS-1001",
            offer_id="invented-offer",
            flight_number="ZZ999",
            origin="LAX",
            destination="ORD",
            price_amount=0,
            idempotency_key="invented",
            current_time=NOW,
        )
    assert env.holds == before_holds

    hold_id = _hold(env)
    approval_id = _approval(env, hold_id)
    env.confirm_rebooking(
        booking_reference="AS-1001",
        hold_id=hold_id,
        approval_id=approval_id,
        idempotency_key="confirm-1",
        current_time=NOW,
    )
    before_holds = dict(env.holds)
    with pytest.raises(StateTransitionError):
        _hold(env, key="second-hold-after-rebooking")
    assert env.holds == before_holds


def test_release_active_hold_restores_booking_and_cannot_release_consumed_hold() -> None:
    env = SimulatedAirlineEnvironment()
    hold_id = _hold(env)
    env.release_hold(hold_id=hold_id, idempotency_key="release-1", current_time=NOW)
    assert env.get_booking("AS-1001").status == BookingStatus.DISRUPTED
    assert env.get_booking("AS-1001").active_hold_id is None
    assert env.holds[hold_id].status.value == "released"

    env = SimulatedAirlineEnvironment()
    consumed_hold = _hold(env)
    approval_id = _approval(env, consumed_hold)
    env.confirm_rebooking(
        booking_reference="AS-1001",
        hold_id=consumed_hold,
        approval_id=approval_id,
        idempotency_key="confirm-before-release",
        current_time=NOW,
    )
    before_booking = env.get_booking("AS-1001")
    with pytest.raises(StateTransitionError):
        env.release_hold(
            hold_id=consumed_hold, idempotency_key="release-consumed", current_time=NOW
        )
    assert env.get_booking("AS-1001") == before_booking
    assert env.holds[consumed_hold].status.value == "confirmed"


def test_idempotency_is_scoped_and_concurrent_confirm_has_one_commit() -> None:
    env = SimulatedAirlineEnvironment()
    hold_id = _hold(env)
    approval_id = _approval(env, hold_id)
    barrier = Barrier(2)

    def confirm() -> dict[str, object]:
        barrier.wait()
        return env.confirm_rebooking(
            booking_reference="AS-1001",
            hold_id=hold_id,
            approval_id=approval_id,
            idempotency_key="same-confirm-key",
            current_time=NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(lambda _: confirm(), range(2)))

    assert first == second
    assert len(env.transactions) == 1
    assert env.get_booking("AS-1001").status == BookingStatus.REBOOKED
    with pytest.raises(IdempotencyConflictError):
        env.idempotency.check_or_register(
            key="same-confirm-key",
            tool_name="booking.confirm_rebooking",
            payload={"tampered": True},
            registered_at=NOW,
        )


def test_approval_registry_scope_validations() -> None:
    from flight_agent_evaluator.environment.errors import (
        ApprovalNotFoundError,
        ApprovalScopeMismatchError,
    )

    env = SimulatedAirlineEnvironment()
    hold_id = _hold(env)
    app_id = _approval(env, hold_id)

    # Nonexistent approval
    with pytest.raises(ApprovalNotFoundError):
        env.approvals.verify_approval_for_mutation(
            approval_id="app-does-not-exist",
            action_type="confirm_rebooking",
            booking_reference="AS-1001",
            mutation_payload={"hold_id": hold_id},
            current_time=NOW,
        )

    # Wrong action type
    with pytest.raises(ApprovalScopeMismatchError, match="does not match"):
        env.approvals.verify_approval_for_mutation(
            approval_id=app_id,
            action_type="wrong_action",
            booking_reference="AS-1001",
            mutation_payload={"hold_id": hold_id},
            current_time=NOW,
        )

    # Wrong booking reference
    with pytest.raises(ApprovalScopeMismatchError, match="booking reference"):
        env.approvals.verify_approval_for_mutation(
            approval_id=app_id,
            action_type="confirm_rebooking",
            booking_reference="AS-9999",
            mutation_payload={"hold_id": hold_id},
            current_time=NOW,
        )

    # Tampered mutation payload
    with pytest.raises(ApprovalScopeMismatchError, match="Mutation payload hash"):
        env.approvals.verify_approval_for_mutation(
            approval_id=app_id,
            action_type="confirm_rebooking",
            booking_reference="AS-1001",
            mutation_payload={"hold_id": "tampered-hold-id"},
            current_time=NOW,
        )

"""Synthetic booking and environment state fixtures for Stage 5 scenarios."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.contracts.base import Money
from flight_agent_evaluator.environment.contracts import (
    ApprovalRequest,
    ApprovalStatus,
    BookingRecord,
    BookingStatus,
    HoldRecord,
    HoldStatus,
)

_REF_TIME = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)


def get_default_booking_fixture() -> BookingRecord:
    """Return synthetic disrupted booking reference AS-1001 (JFK -> LHR)."""
    return BookingRecord(
        booking_reference="AS-1001",
        passenger_name="Jane Doe",
        current_flight_number="AS142",
        origin="JFK",
        destination="LHR",
        scheduled_departure=_REF_TIME + timedelta(hours=2),
        status=BookingStatus.DISRUPTED,
    )


def get_default_hold_fixture(
    booking_reference: str = "AS-1001",
    expires_in_minutes: int = 30,
) -> HoldRecord:
    """Return synthetic active inventory hold for AS-1001 on alternative offer offer-alt-1."""
    return HoldRecord(
        hold_id="hold-9901",
        booking_reference=booking_reference,
        offer_id="offer-alt-1",
        flight_number="AS144",
        origin="JFK",
        destination="LHR",
        price=Money(amount=550.0, currency="USD"),
        placed_at=_REF_TIME,
        expires_at=_REF_TIME + timedelta(minutes=expires_in_minutes),
        status=HoldStatus.ACTIVE,
    )


def get_default_approval_fixture(
    booking_reference: str = "AS-1001",
    action_type: str = "confirm_rebooking",
    mutation_payload: dict[str, object] | None = None,
    status: ApprovalStatus = ApprovalStatus.APPROVED,
    expires_in_minutes: int = 60,
) -> ApprovalRequest:
    """Return synthetic approval request for confirming a rebooking."""
    payload = mutation_payload or {
        "booking_reference": booking_reference,
        "hold_id": "hold-9901",
    }
    p_hash = canonical_hash(payload)

    return ApprovalRequest(
        approval_id="appr-7701",
        booking_reference=booking_reference,
        action_type=action_type,
        requested_offer_id="offer-alt-1",
        payload_hash=p_hash,
        reason="Flight AS142 cancelled due to maintenance.",
        requested_at=_REF_TIME,
        expires_at=_REF_TIME + timedelta(minutes=expires_in_minutes),
        status=status,
        decided_at=_REF_TIME + timedelta(minutes=5) if status == ApprovalStatus.APPROVED else None,
    )

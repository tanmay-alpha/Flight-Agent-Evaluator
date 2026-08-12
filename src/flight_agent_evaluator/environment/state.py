"""Explicit state machine rules and transitions for the simulated environment."""

from __future__ import annotations

from flight_agent_evaluator.environment.contracts import BookingStatus, HoldStatus
from flight_agent_evaluator.environment.errors import StateTransitionError

# Valid booking status transitions: source_status -> set of allowed target statuses
_VALID_BOOKING_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.UNBOOKED: {BookingStatus.BOOKED},
    BookingStatus.BOOKED: {BookingStatus.DISRUPTED, BookingStatus.CANCELLED},
    BookingStatus.DISRUPTED: {BookingStatus.HOLD_PLACED, BookingStatus.CANCELLED},
    BookingStatus.HOLD_PLACED: {
        BookingStatus.REBOOKED,
        BookingStatus.DISRUPTED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.REBOOKED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
}

# Valid hold status transitions
_VALID_HOLD_TRANSITIONS: dict[HoldStatus, set[HoldStatus]] = {
    HoldStatus.ACTIVE: {HoldStatus.CONFIRMED, HoldStatus.RELEASED, HoldStatus.EXPIRED},
    HoldStatus.CONFIRMED: set(),
    HoldStatus.RELEASED: set(),
    HoldStatus.EXPIRED: set(),
}


def validate_booking_transition(current: BookingStatus, target: BookingStatus) -> None:
    """Validate that a booking status transition is permitted.

    Raises:
        StateTransitionError: If the transition is invalid.
    """
    allowed = _VALID_BOOKING_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise StateTransitionError(
            f"Invalid booking status transition from '{current.value}' to '{target.value}'. "
            f"Allowed transitions from '{current.value}': {[s.value for s in allowed]}."
        )


def validate_hold_transition(current: HoldStatus, target: HoldStatus) -> None:
    """Validate that a hold status transition is permitted.

    Raises:
        StateTransitionError: If the transition is invalid.
    """
    allowed = _VALID_HOLD_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise StateTransitionError(
            f"Invalid hold status transition from '{current.value}' to '{target.value}'. "
            f"Allowed transitions from '{current.value}': {[s.value for s in allowed]}."
        )

"""Booking and approval contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from flight_agent_evaluator.contracts.aviation import FlightOffer
from flight_agent_evaluator.contracts.base import (
    ContractModel,
    Money,
    SchemaVersion,
)

# ---------------------------------------------------------------------------
# Passenger and booking references
# ---------------------------------------------------------------------------


class PassengerReference(ContractModel):
    """Reference to a passenger without real personal information."""

    reference_id: str = Field(min_length=1)
    passenger_type: str = Field(default="adult", min_length=1)


class BookingReference(ContractModel):
    """A booking reference (PNR-style, synthetic)."""

    record_locator: str = Field(min_length=1)
    airline_iata: str = Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z0-9]{2}$",
    )


# ---------------------------------------------------------------------------
# Booking state
# ---------------------------------------------------------------------------

BookingState = str  # Literal["hold", "confirmed", "cancelled", "expired", "ticketed"]


# ---------------------------------------------------------------------------
# Booking snapshot
# ---------------------------------------------------------------------------


class BookingSnapshot(ContractModel):
    """Immutable snapshot of a booking's current state."""

    booking_reference: BookingReference  # type: ignore[valid-type]
    state: str = Field(min_length=1)
    flight_offers: tuple[FlightOffer, ...]  # type: ignore[valid-type]
    passengers: tuple[PassengerReference, ...]  # type: ignore[valid-type]
    total_price: Money  # type: ignore[valid-type]
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    created_at: datetime
    expires_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Scoped action
# ---------------------------------------------------------------------------


class ScopedAction(ContractModel):
    """A proposed action with explicit scope."""

    action: str = Field(min_length=1)
    scope: str = Field(min_length=1, description="Explicit scope of the action")
    payload: dict[str, Any] = Field(
        description="Action payload (JSON-compatible)",
    )


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------


class IdempotencyKey(ContractModel):
    """Deterministic key for idempotent operations."""

    key: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 hash")
    namespace: str = Field(default="default", description="Namespace for the key")


# ---------------------------------------------------------------------------
# Approval state
# ---------------------------------------------------------------------------

ApprovalState = str  # Literal["pending", "granted", "denied", "expired"]


# ---------------------------------------------------------------------------
# Approval request
# ---------------------------------------------------------------------------


class ApprovalRequest(ContractModel):
    """A request for human approval of a proposed action."""

    schema_version: SchemaVersion = SchemaVersion(major=1, minor=0, patch=0)  # type: ignore[valid-type]
    request_id: str = Field(min_length=1)
    proposed_action: ScopedAction  # type: ignore[valid-type]
    payload_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hash of the proposed action payload",
    )
    created_at: datetime
    expires_at: datetime
    state: str = Field(default="pending")


# ---------------------------------------------------------------------------
# Approval decision
# ---------------------------------------------------------------------------


class ApprovalDecision(ContractModel):
    """The outcome of an approval request."""

    request_id: str = Field(min_length=1)
    state: str
    decided_at: datetime
    decided_by: str | None = Field(default=None)
    notes: str | None = Field(default=None)

"""Contracts for the simulated transactional airline environment.

All models inherit from ContractModel (strict, frozen, forbid extra fields).
Schema version: environment-schema-v1
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from flight_agent_evaluator.contracts.base import ContractModel, Money
from flight_agent_evaluator.contracts.common import (
    IATAAirportCode,
    NonEmptyIdentifier,
    SHA256Digest,
)

ENVIRONMENT_SCHEMA_VERSION: str = "environment-schema-v1"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BookingStatus(StrEnum):
    """Lifecycle status of a passenger booking."""

    UNBOOKED = "unbooked"
    BOOKED = "booked"
    DISRUPTED = "disrupted"
    HOLD_PLACED = "hold_placed"
    REBOOKED = "rebooked"
    CANCELLED = "cancelled"


class HoldStatus(StrEnum):
    """Status of an inventory hold on an alternative flight offer."""

    ACTIVE = "active"
    CONFIRMED = "confirmed"
    RELEASED = "released"
    EXPIRED = "expired"


class ApprovalStatus(StrEnum):
    """Status of a human/supervisor approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class TransactionStatus(StrEnum):
    """Status of a state mutation transaction."""

    INITIATED = "initiated"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    AMBIGUOUS = "ambiguous"


# ---------------------------------------------------------------------------
# State Models
# ---------------------------------------------------------------------------


class HoldRecord(ContractModel):
    """Record of an active or historical inventory hold on a flight offer."""

    hold_id: NonEmptyIdentifier
    booking_reference: NonEmptyIdentifier
    offer_id: NonEmptyIdentifier
    flight_number: str = Field(..., min_length=2)
    origin: IATAAirportCode
    destination: IATAAirportCode
    price: Money
    placed_at: datetime
    expires_at: datetime
    status: HoldStatus = Field(default=HoldStatus.ACTIVE)

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> HoldRecord:
        if self.placed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Timestamps in HoldRecord must be timezone-aware.")
        if self.expires_at <= self.placed_at:
            raise ValueError("expires_at must be strictly after placed_at.")
        return self

    def is_expired(self, current_time: datetime) -> bool:
        return current_time >= self.expires_at


class ApprovalRequest(ContractModel):
    """Request for supervisor/human approval before a sensitive state mutation."""

    approval_id: NonEmptyIdentifier
    booking_reference: NonEmptyIdentifier
    action_type: str = Field(..., description="Action type, e.g. 'rebook_flight'.")
    requested_offer_id: NonEmptyIdentifier
    payload_hash: SHA256Digest
    reason: str = Field(..., min_length=1)
    requested_at: datetime
    expires_at: datetime
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    decision_reason: str | None = None
    decided_at: datetime | None = None

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> ApprovalRequest:
        if self.requested_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Timestamps in ApprovalRequest must be timezone-aware.")
        if self.decided_at and self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware if present.")
        return self

    def is_expired(self, current_time: datetime) -> bool:
        return current_time >= self.expires_at


class BookingRecord(ContractModel):
    """Current state of a simulated passenger flight booking."""

    booking_reference: NonEmptyIdentifier
    passenger_name: str = Field(..., min_length=1)
    current_flight_number: str = Field(..., min_length=2)
    origin: IATAAirportCode
    destination: IATAAirportCode
    scheduled_departure: datetime
    status: BookingStatus = Field(default=BookingStatus.BOOKED)
    rebooked_flight_number: str | None = None
    rebooked_departure: datetime | None = None
    active_hold_id: str | None = None
    active_approval_id: str | None = None

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> BookingRecord:
        if self.scheduled_departure.tzinfo is None:
            raise ValueError("scheduled_departure must be timezone-aware.")
        if self.rebooked_departure and self.rebooked_departure.tzinfo is None:
            raise ValueError("rebooked_departure must be timezone-aware if present.")
        return self


class RebookingTransaction(ContractModel):
    """Record of a committed or attempted rebooking state mutation."""

    transaction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    booking_reference: NonEmptyIdentifier
    hold_id: NonEmptyIdentifier
    approval_id: NonEmptyIdentifier
    idempotency_key: NonEmptyIdentifier
    payload_hash: SHA256Digest
    status: TransactionStatus = Field(default=TransactionStatus.COMMITTED)
    executed_at: datetime
    result_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> RebookingTransaction:
        if self.executed_at.tzinfo is None:
            raise ValueError("executed_at must be timezone-aware.")
        return self


class IdempotencyRecord(ContractModel):
    """Registry record tracking an idempotency key and its cached result."""

    key: NonEmptyIdentifier
    payload_hash: SHA256Digest
    tool_name: str
    result_payload: dict[str, Any]
    registered_at: datetime

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> IdempotencyRecord:
        if self.registered_at.tzinfo is None:
            raise ValueError("registered_at must be timezone-aware.")
        return self

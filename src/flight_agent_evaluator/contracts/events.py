"""Event contracts (versioned envelope + discriminated union)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from flight_agent_evaluator.contracts.aviation import (
    FlightOffer,
    FlightSearchRequest,
    FlightStatusObservation,
)
from flight_agent_evaluator.contracts.base import (
    ContractModel,
    SchemaVersion,
)
from flight_agent_evaluator.contracts.booking import (
    ApprovalDecision,
    ApprovalRequest,
)
from flight_agent_evaluator.contracts.common import (
    NonEmptyIdentifier,
    UtcDateTime,
)
from flight_agent_evaluator.contracts.providers import ProviderConflict

# ---------------------------------------------------------------------------
# Event envelope (versioned)
# ---------------------------------------------------------------------------

EVENT_SCHEMA_VERSION = SchemaVersion(major=1, minor=0, patch=0)


class EventEnvelope(ContractModel):
    """Versioned envelope around all event payloads."""

    schema_version: SchemaVersion = EVENT_SCHEMA_VERSION
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = Field(min_length=1)
    event_version: int = Field(default=1, ge=1)
    run_id: uuid.UUID
    correlation_id: uuid.UUID | None = Field(default=None)
    causation_id: uuid.UUID | None = Field(default=None)
    occurrence_time: datetime = Field(default_factory=UtcDateTime.now)
    payload: dict[str, Any] = Field(default_factory=dict)  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class FlightStatusRequestedPayload(ContractModel):
    query: dict[str, Any]  # type: ignore[valid-type]


class FlightStatusObservedPayload(ContractModel):
    observation: FlightStatusObservation  # type: ignore[valid-type]


class AlternativeFlightsRequestedPayload(ContractModel):
    request: FlightSearchRequest  # type: ignore[valid-type]


class AlternativeFlightsReturnedPayload(ContractModel):
    request: FlightSearchRequest  # type: ignore[valid-type]
    offers: tuple[FlightOffer, ...]  # type: ignore[valid-type]


class ProviderCallFailedPayload(ContractModel):
    provider_name: str
    error_type: str
    message: str


class ProviderConflictDetectedPayload(ContractModel):
    conflict: ProviderConflict  # type: ignore[valid-type]


class ApprovalRequestedPayload(ContractModel):
    approval: ApprovalRequest  # type: ignore[valid-type]


class ApprovalGrantedPayload(ContractModel):
    decision: ApprovalDecision  # type: ignore[valid-type]


class ApprovalDeniedPayload(ContractModel):
    decision: ApprovalDecision  # type: ignore[valid-type]


class ApprovalExpiredPayload(ContractModel):
    request_id: NonEmptyIdentifier  # type: ignore[valid-type]


class BookingHoldCreatedPayload(ContractModel):
    booking_id: NonEmptyIdentifier  # type: ignore[valid-type]
    expires_at: datetime


class RebookingConfirmedPayload(ContractModel):
    original_booking_id: NonEmptyIdentifier  # type: ignore[valid-type]
    new_offer_id: NonEmptyIdentifier  # type: ignore[valid-type]


class RefundRequestedPayload(ContractModel):
    booking_id: NonEmptyIdentifier  # type: ignore[valid-type]
    reason: str | None = None


class NotificationQueuedPayload(ContractModel):
    notification_id: NonEmptyIdentifier  # type: ignore[valid-type]
    channel: Literal["email", "sms", "push"]


class ReplayStartedPayload(ContractModel):
    run_id: uuid.UUID
    scenario_id: NonEmptyIdentifier  # type: ignore[valid-type]


class ReplayCompletedPayload(ContractModel):
    run_id: uuid.UUID
    status: Literal["ok", "diverged"]


class EvaluationCompletedPayload(ContractModel):
    evaluation_id: uuid.UUID
    status: Literal["passed", "failed", "inconclusive"]


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------


class DomainEvent(ContractModel):
    """A versioned, discriminated event."""

    schema_version: SchemaVersion = EVENT_SCHEMA_VERSION
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_version: int = Field(default=1, ge=1)
    run_id: uuid.UUID
    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    occurrence_time: datetime = Field(default_factory=UtcDateTime.now)

    discriminator: Literal[
        "flight_status_requested",
        "flight_status_observed",
        "alternative_flights_requested",
        "alternative_flights_returned",
        "provider_call_failed",
        "provider_conflict_detected",
        "approval_requested",
        "approval_granted",
        "approval_denied",
        "approval_expired",
        "booking_hold_created",
        "rebooking_confirmed",
        "refund_requested",
        "notification_queued",
        "replay_started",
        "replay_completed",
        "evaluation_completed",
    ] = Field(description="Discriminator for the event type")

    payload: Any = Field(default=None)  # type: ignore[valid-type]


DomainEvent.model_rebuild()

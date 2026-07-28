"""Event contracts (versioned envelope + discriminated union).

This module defines the canonical event envelope plus a discriminated union
of payload models. Each event type has exactly one payload model, registered
in :data:`PAYLOAD_MODELS`. Downstream code should resolve the payload model
via this registry rather than hard-coded if/elif chains.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

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
# Event schema constants
# ---------------------------------------------------------------------------

EVENT_SCHEMA_MAJOR = 1
EVENT_SCHEMA_MINOR = 0
EVENT_SCHEMA_PATCH = 0
EVENT_SCHEMA_VERSION = SchemaVersion(
    major=EVENT_SCHEMA_MAJOR,
    minor=EVENT_SCHEMA_MINOR,
    patch=EVENT_SCHEMA_PATCH,
)


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class FlightStatusRequestedPayload(ContractModel):
    """Query parameters for a flight status lookup."""

    query: dict[str, Any]


class FlightStatusObservedPayload(ContractModel):
    """Observation of a flight status."""

    observation: FlightStatusObservation


class AlternativeFlightsRequestedPayload(ContractModel):
    """Search request for alternative flights."""

    request: FlightSearchRequest


class AlternativeFlightsReturnedPayload(ContractModel):
    """Search results for alternative flights."""

    request: FlightSearchRequest
    offers: tuple[FlightOffer, ...]


class ProviderCallFailedPayload(ContractModel):
    """Provider call failed."""

    provider_name: str
    error_type: str
    message: str


class ProviderConflictDetectedPayload(ContractModel):
    """A provider conflict was detected."""

    conflict: ProviderConflict


class ApprovalRequestedPayload(ContractModel):
    """An approval request was created."""

    approval: ApprovalRequest


class ApprovalGrantedPayload(ContractModel):
    """An approval was granted."""

    decision: ApprovalDecision


class ApprovalDeniedPayload(ContractModel):
    """An approval was denied."""

    decision: ApprovalDecision


class ApprovalExpiredPayload(ContractModel):
    """An approval request expired."""

    request_id: NonEmptyIdentifier


class BookingHoldCreatedPayload(ContractModel):
    """A booking hold was created."""

    booking_id: NonEmptyIdentifier
    expires_at: datetime


class RebookingConfirmedPayload(ContractModel):
    """A rebooking was confirmed."""

    original_booking_id: NonEmptyIdentifier
    new_offer_id: NonEmptyIdentifier


class RefundRequestedPayload(ContractModel):
    """A refund was requested."""

    booking_id: NonEmptyIdentifier
    reason: str | None = None


class NotificationQueuedPayload(ContractModel):
    """A notification was queued for delivery."""

    notification_id: NonEmptyIdentifier
    channel: Literal["email", "sms", "push"]


class ReplayStartedPayload(ContractModel):
    """A scenario replay run started."""

    run_id: uuid.UUID
    scenario_id: NonEmptyIdentifier


class ReplayCompletedPayload(ContractModel):
    """A scenario replay run completed."""

    run_id: uuid.UUID
    status: Literal["ok", "diverged"]


class EvaluationCompletedPayload(ContractModel):
    """An evaluation completed."""

    evaluation_id: uuid.UUID
    status: Literal["passed", "failed", "inconclusive"]


# ---------------------------------------------------------------------------
# Payload registry (discriminator -> payload model)
# ---------------------------------------------------------------------------

PAYLOAD_MODELS: dict[str, type[ContractModel]] = {
    "flight_status_requested": FlightStatusRequestedPayload,
    "flight_status_observed": FlightStatusObservedPayload,
    "alternative_flights_requested": AlternativeFlightsRequestedPayload,
    "alternative_flights_returned": AlternativeFlightsReturnedPayload,
    "provider_call_failed": ProviderCallFailedPayload,
    "provider_conflict_detected": ProviderConflictDetectedPayload,
    "approval_requested": ApprovalRequestedPayload,
    "approval_granted": ApprovalGrantedPayload,
    "approval_denied": ApprovalDeniedPayload,
    "approval_expired": ApprovalExpiredPayload,
    "booking_hold_created": BookingHoldCreatedPayload,
    "rebooking_confirmed": RebookingConfirmedPayload,
    "refund_requested": RefundRequestedPayload,
    "notification_queued": NotificationQueuedPayload,
    "replay_started": ReplayStartedPayload,
    "replay_completed": ReplayCompletedPayload,
    "evaluation_completed": EvaluationCompletedPayload,
}


# ---------------------------------------------------------------------------
# Envelope (raw, free-form payload)
# ---------------------------------------------------------------------------


class EventEnvelope(ContractModel):
    """Versioned envelope around any event payload.

    For typed payloads, use :class:`DomainEvent` instead.
    """

    schema_version: SchemaVersion = EVENT_SCHEMA_VERSION
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = Field(min_length=1)
    event_version: int = Field(default=1, ge=1)
    run_id: uuid.UUID
    correlation_id: uuid.UUID | None = Field(default=None)
    causation_id: uuid.UUID | None = Field(default=None)
    occurrence_time: datetime = Field(default_factory=UtcDateTime.now)
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Domain event (typed, discriminated)
# ---------------------------------------------------------------------------


class DomainEvent(ContractModel):
    """A versioned, typed event with discriminated payload.

    ``event_type`` doubles as the discriminator; payloads are coerced into
    the matching payload model from :data:`PAYLOAD_MODELS`.
    """

    schema_version: SchemaVersion = EVENT_SCHEMA_VERSION
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = Field(min_length=1)
    event_version: int = Field(default=1, ge=1)
    run_id: uuid.UUID
    correlation_id: uuid.UUID | None = Field(default=None)
    causation_id: uuid.UUID | None = Field(default=None)
    occurrence_time: datetime = Field(default_factory=UtcDateTime.now)
    payload: Any = Field(default=None)

    @model_validator(mode="after")
    def _validate_event(self) -> DomainEvent:
        """Validate that event_type is known when payload is provided."""

        if self.payload is not None and self.event_type not in PAYLOAD_MODELS:
            raise ValueError(
                f"Unknown event_type '{self.event_type}'. "
                f"Must be one of: {sorted(PAYLOAD_MODELS.keys())}"
            )
        return self

    @model_validator(mode="after")
    def _coerce_payload(self) -> DomainEvent:
        """Coerce payload into the matching payload model from PAYLOAD_MODELS."""

        if (
            self.event_type in PAYLOAD_MODELS
            and self.payload is not None
            and not isinstance(self.payload, PAYLOAD_MODELS[self.event_type])
        ):
            payload_model = PAYLOAD_MODELS[self.event_type]
            if isinstance(self.payload, dict):
                coerced = payload_model.model_validate(self.payload)
                object.__setattr__(self, "payload", coerced)
        return self


__all__ = [
    "EVENT_SCHEMA_MAJOR",
    "EVENT_SCHEMA_MINOR",
    "EVENT_SCHEMA_PATCH",
    "EVENT_SCHEMA_VERSION",
    "PAYLOAD_MODELS",
    "ApprovalDeniedPayload",
    "ApprovalExpiredPayload",
    "ApprovalGrantedPayload",
    "ApprovalRequestedPayload",
    "AlternativeFlightsRequestedPayload",
    "AlternativeFlightsReturnedPayload",
    "BookingHoldCreatedPayload",
    "DomainEvent",
    "EvaluationCompletedPayload",
    "EventEnvelope",
    "FlightStatusObservedPayload",
    "FlightStatusRequestedPayload",
    "NotificationQueuedPayload",
    "ProviderCallFailedPayload",
    "ProviderConflictDetectedPayload",
    "RebookingConfirmedPayload",
    "RefundRequestedPayload",
    "ReplayCompletedPayload",
    "ReplayStartedPayload",
]

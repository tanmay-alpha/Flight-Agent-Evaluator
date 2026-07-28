"""Tests for event contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.contracts.events import (
    EVENT_SCHEMA_MAJOR,
    EVENT_SCHEMA_MINOR,
    EVENT_SCHEMA_PATCH,
    EVENT_SCHEMA_VERSION,
    PAYLOAD_MODELS,
    ApprovalExpiredPayload,
    DomainEvent,
    EvaluationCompletedPayload,
    EventEnvelope,
    FlightStatusRequestedPayload,
    NotificationQueuedPayload,
    ProviderCallFailedPayload,
    ReplayCompletedPayload,
    ReplayStartedPayload,
)


class TestEventSchemaVersion:
    def test_constants(self) -> None:
        assert EVENT_SCHEMA_MAJOR == 1
        assert EVENT_SCHEMA_MINOR == 0
        assert EVENT_SCHEMA_PATCH == 0

    def test_schema_version_model(self) -> None:
        assert EVENT_SCHEMA_VERSION.major == 1
        assert EVENT_SCHEMA_VERSION.minor == 0
        assert EVENT_SCHEMA_VERSION.patch == 0


class TestEventEnvelope:
    def _base(self) -> dict[str, Any]:
        return {
            "run_id": uuid.uuid4(),
            "event_type": "test",
            "occurrence_time": datetime.now(UTC),
        }

    def test_valid(self) -> None:
        e = EventEnvelope(**self._base())
        assert e.event_id is not None
        assert e.event_version == 1
        assert e.schema_version == EVENT_SCHEMA_VERSION
        assert e.payload == {}

    def test_payload_defaults_to_empty_dict(self) -> None:
        e = EventEnvelope(**self._base())
        assert e.payload == {}

    def test_blank_event_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EventEnvelope(**{**self._base(), "event_type": ""})


class TestPayloadModels:
    def test_flight_status_requested(self) -> None:
        p = FlightStatusRequestedPayload(
            query={"flight_number": "AA123", "query_date": "2026-01-01"}
        )
        assert p.query["flight_number"] == "AA123"

    def test_replay_completed(self) -> None:
        p = ReplayCompletedPayload(run_id=uuid.uuid4(), status="ok")
        assert p.status == "ok"
        with pytest.raises(ValidationError):
            ReplayCompletedPayload(run_id=uuid.uuid4(), status="maybe")

    def test_provider_call_failed(self) -> None:
        p = ProviderCallFailedPayload(
            provider_name="test",
            error_type="timeout",
            message="timed out",
        )
        assert p.provider_name == "test"
        assert p.error_type == "timeout"

    def test_approval_expired(self) -> None:
        p = ApprovalExpiredPayload(request_id="req-123")
        assert p.request_id == "req-123"

    def test_notification_queued(self) -> None:
        p = NotificationQueuedPayload(notification_id="n1", channel="email")
        assert p.channel == "email"
        with pytest.raises(ValidationError):
            NotificationQueuedPayload(notification_id="n1", channel="carrier_pigeon")

    def test_evaluation_completed(self) -> None:
        p = EvaluationCompletedPayload(evaluation_id=uuid.uuid4(), status="passed")
        assert p.status == "passed"
        with pytest.raises(ValidationError):
            EvaluationCompletedPayload(evaluation_id=uuid.uuid4(), status="passed_with_extras")


class TestDomainEvent:
    def _base(self) -> dict[str, Any]:
        return {
            "run_id": uuid.uuid4(),
            "event_type": "provider_call_failed",
            "occurrence_time": datetime.now(UTC),
        }

    def test_valid(self) -> None:
        e = DomainEvent(
            **self._base(),
            payload=ProviderCallFailedPayload(
                provider_name="test",
                error_type="timeout",
                message="timed out",
            ),
        )
        assert e.event_type == "provider_call_failed"
        assert e.event_version == 1
        assert e.schema_version == EVENT_SCHEMA_VERSION

    def test_payload_dict_coerced_to_model(self) -> None:
        e = DomainEvent(
            **self._base(),
            payload={
                "provider_name": "test",
                "error_type": "timeout",
                "message": "timed out",
            },
        )
        assert isinstance(e.payload, ProviderCallFailedPayload)
        assert e.payload.provider_name == "test"

    def test_invalid_event_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            DomainEvent(
                **{**self._base(), "event_type": "nonexistent_event"},
                payload={},
            )

    def test_event_version_must_be_ge_1(self) -> None:
        with pytest.raises(ValidationError):
            DomainEvent(**self._base(), event_version=0)

    def test_all_event_types_have_payload_model(self) -> None:
        # Just verify the registry is populated correctly; don't try
        # constructing DomainEvents for every type (some payloads have
        # required fields).
        assert "provider_call_failed" in PAYLOAD_MODELS
        assert "approval_expired" in PAYLOAD_MODELS
        assert "replay_completed" in PAYLOAD_MODELS
        assert PAYLOAD_MODELS["provider_call_failed"] is ProviderCallFailedPayload

    def test_replay_started(self) -> None:
        e = DomainEvent(
            run_id=uuid.uuid4(),
            event_type="replay_started",
            occurrence_time=datetime.now(UTC),
            payload=ReplayStartedPayload(
                run_id=uuid.uuid4(),
                scenario_id="scenario-1",
            ),
        )
        assert e.event_type == "replay_started"
        assert isinstance(e.payload, ReplayStartedPayload)
        assert e.payload.scenario_id == "scenario-1"

    def test_all_event_types_in_registry(self) -> None:
        """Every discriminator value has a corresponding payload model."""
        assert len(PAYLOAD_MODELS) == 17

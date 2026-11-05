"""Scenario contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from flight_agent_evaluator.contracts.base import (
    ContractModel,
    RawPayloadReference,
    SchemaVersion,
)
from flight_agent_evaluator.contracts.common import (
    IATAAirportCode,
    ISOCurrencyCode,
    NonEmptyIdentifier,
    PositiveInt,
    SafeIdentifier,
)
from flight_agent_evaluator.contracts.evaluation import Assertion
from flight_agent_evaluator.contracts.faults import FaultSpec
from flight_agent_evaluator.recording.contracts import ScriptedTrajectory

ScenarioApprovalDecision = Literal["approved", "denied", "pending", "expired"]
"""Decision the simulated supervisor returns for every approval request."""


class _StrictContract(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, strict=True)


class EnvironmentBookingSetup(_StrictContract):
    """A synthetic booking present in the simulated airline at scenario start."""

    booking_reference: NonEmptyIdentifier  # type: ignore[valid-type]
    passenger_name: str = Field(min_length=1)
    current_flight_number: str = Field(min_length=2)
    origin: IATAAirportCode  # type: ignore[valid-type]
    destination: IATAAirportCode  # type: ignore[valid-type]
    scheduled_departure: datetime = Field(strict=False)
    status: Literal["disrupted", "rebooked"] = "disrupted"
    rebooked_flight_number: str | None = Field(default=None, min_length=2)

    @model_validator(mode="after")
    def _consistent_status(self) -> EnvironmentBookingSetup:
        if self.scheduled_departure.tzinfo is None:
            raise ValueError("scheduled_departure must be timezone-aware")
        if (self.status == "rebooked") != (self.rebooked_flight_number is not None):
            raise ValueError("rebooked_flight_number is required exactly when status is 'rebooked'")
        return self


class EnvironmentOfferSetup(_StrictContract):
    """An alternative-flight offer present in the authoritative synthetic inventory."""

    offer_id: NonEmptyIdentifier  # type: ignore[valid-type]
    flight_number: str = Field(min_length=2)
    origin: IATAAirportCode  # type: ignore[valid-type]
    destination: IATAAirportCode  # type: ignore[valid-type]
    price_amount: float = Field(gt=0)
    price_currency: ISOCurrencyCode = "USD"  # type: ignore[valid-type]


class PriceChangeAfterApproval(_StrictContract):
    """Inventory reprices a held offer immediately after its first approval is issued."""

    offer_id: NonEmptyIdentifier  # type: ignore[valid-type]
    new_price_amount: float = Field(gt=0)


class ScenarioEnvironment(_StrictContract):
    """Explicit simulated-airline configuration for a transactional scenario.

    Absent ``approval_decision`` means no supervisor ever approves: approval
    requests resolve to ``denied`` (fail closed).
    """

    bookings: tuple[EnvironmentBookingSetup, ...] = Field(default_factory=tuple, strict=False)
    offers: tuple[EnvironmentOfferSetup, ...] = Field(default_factory=tuple, strict=False)
    approval_decision: ScenarioApprovalDecision | None = None
    hold_expired: bool = False
    alternative_disappears: bool = False
    response_lost_on_confirm: bool = False
    price_change_after_approval: PriceChangeAfterApproval | None = None

    @model_validator(mode="after")
    def _unique_resources(self) -> ScenarioEnvironment:
        refs = [b.booking_reference for b in self.bookings]
        if len(refs) != len(set(refs)):
            raise ValueError("environment.bookings contains duplicate booking_reference values")
        offer_ids = [o.offer_id for o in self.offers]
        if len(offer_ids) != len(set(offer_ids)):
            raise ValueError("environment.offers contains duplicate offer_id values")
        change = self.price_change_after_approval
        if change is not None and change.offer_id not in offer_ids:
            raise ValueError("price_change_after_approval.offer_id must reference a declared offer")
        return self


class ScenarioIdentifier(ContractModel):
    """Stable, globally unique identifier for a scenario."""

    id: SafeIdentifier  # type: ignore[valid-type]
    version: int = Field(ge=1, default=1)


class ScenarioMetadata(ContractModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    author: str | None = None


class ScenarioFixtureReference(ContractModel):
    fixture_name: NonEmptyIdentifier  # type: ignore[valid-type]
    raw_payload_reference: RawPayloadReference  # type: ignore[valid-type]


class ScenarioLimits(ContractModel):
    tool_call_limit: PositiveInt  # type: ignore[valid-type]
    time_limit_seconds: PositiveInt  # type: ignore[valid-type]


class ScenarioStep(ContractModel):
    step_id: NonEmptyIdentifier  # type: ignore[valid-type]
    description: str = Field(min_length=1)
    initial_message: str | None = None


class BenchmarkScenario(ContractModel):
    """A benchmark scenario specification.

    Scenario files are machine-readable and strict. Executable Python
    is never embedded.
    """

    schema_version: SchemaVersion = SchemaVersion(major=1, minor=0, patch=0)  # type: ignore[valid-type]
    scenario_id: ScenarioIdentifier  # type: ignore[valid-type]
    metadata: ScenarioMetadata  # type: ignore[valid-type]
    initial_state: dict[str, Any] = Field(default_factory=dict)  # type: ignore[valid-type]
    fixture_references: tuple[ScenarioFixtureReference, ...] = Field(default_factory=tuple)  # type: ignore[valid-type]
    faults: tuple[FaultSpec, ...] = Field(default_factory=tuple)  # type: ignore[valid-type]
    steps: tuple[ScenarioStep, ...] = Field(default_factory=tuple)  # type: ignore[valid-type]
    limits: ScenarioLimits  # type: ignore[valid-type]
    seed: int = Field(default=0)
    reference_time: str | None = Field(default=None)
    assertions: tuple[Assertion, ...] = Field(default_factory=tuple)  # type: ignore[valid-type]
    trajectory: ScriptedTrajectory  # type: ignore[valid-type]
    scenario_mode: str = Field(default="read_only")
    allowed_tools: tuple[NonEmptyIdentifier, ...] | None = None  # type: ignore[valid-type]
    environment: ScenarioEnvironment | None = None

    @model_validator(mode="after")
    def _non_empty_steps(self) -> BenchmarkScenario:
        if not self.steps:
            raise ValueError("BenchmarkScenario must have at least one step")
        if self.allowed_tools is not None:
            if not self.allowed_tools:
                raise ValueError("allowed_tools must not be empty when present")
            if len(set(self.allowed_tools)) != len(self.allowed_tools):
                raise ValueError("allowed_tools must not contain duplicates")
        if self.environment is not None and self.scenario_mode != "transactional":
            raise ValueError("environment configuration requires scenario_mode 'transactional'")
        return self

    def canonical_digest(self) -> str:
        """SHA-256 digest of benchmark scenario specification."""
        import hashlib
        import json

        data = self.model_dump(mode="json")
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

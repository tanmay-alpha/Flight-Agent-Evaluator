"""Scenario contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from flight_agent_evaluator.contracts.base import (
    ContractModel,
    RawPayloadReference,
    SchemaVersion,
)
from flight_agent_evaluator.contracts.common import (
    NonEmptyIdentifier,
    PositiveInt,
)
from flight_agent_evaluator.contracts.evaluation import Assertion
from flight_agent_evaluator.contracts.faults import FaultSpec
from flight_agent_evaluator.recording.contracts import ScriptedTrajectory


class ScenarioIdentifier(ContractModel):
    """Stable, globally unique identifier for a scenario."""

    id: NonEmptyIdentifier  # type: ignore[valid-type]
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

    @model_validator(mode="after")
    def _non_empty_steps(self) -> BenchmarkScenario:
        if not self.steps:
            raise ValueError("BenchmarkScenario must have at least one step")
        return self

    def canonical_digest(self) -> str:
        """SHA-256 digest of benchmark scenario specification."""
        import hashlib
        import json

        data = self.model_dump(mode="json")
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

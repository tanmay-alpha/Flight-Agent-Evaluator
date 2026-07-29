"""Recording contracts for the Phase 2 runtime.

These contracts describe the entries written to the append-only hash-chained
journal that records every tool call, result, event, trace span, and state
snapshot during an evaluation run.

Recording schema version: 1
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import (
    NonEmptyIdentifier,
    PositiveInt,
    SHA256Digest,
)
from flight_agent_evaluator.contracts.tools import ToolCall, ToolResult

# ---------------------------------------------------------------------------
# Recording schema version
# ---------------------------------------------------------------------------

RECORDING_SCHEMA_VERSION: int = 1

JournalEntryType = Literal[
    "run_started",
    "scenario_loaded",
    "driver_started",
    "tool_call",
    "tool_result",
    "fault_injected",
    "domain_event",
    "trace_span",
    "state_snapshot",
    "driver_completed",
    "replay_report",
    "evaluation_result",
    "run_completed",
]


# ---------------------------------------------------------------------------
# Journal entry
# ---------------------------------------------------------------------------


class JournalEntry(ContractModel):
    """A single append-only entry in the run journal."""

    model_config = ConfigDict(extra="forbid")

    v: int = Field(default=RECORDING_SCHEMA_VERSION, ge=1)
    seq: PositiveInt
    id: uuid.UUID
    type: JournalEntryType
    run_id: uuid.UUID
    correlation_id: str
    time: datetime
    payload: dict[str, Any]
    prev_hash: str
    hash: str

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> JournalEntry:
        if self.time.tzinfo is None or self.time.utcoffset() is None:
            raise ValueError(
                f"JournalEntry time must be timezone-aware, got {self.time!r}"
            )
        return self


# ---------------------------------------------------------------------------
# Run recording summary
# ---------------------------------------------------------------------------


class RunRecording(ContractModel):
    """Summary metadata for a complete run recording."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=RECORDING_SCHEMA_VERSION, ge=1)
    run_id: uuid.UUID
    scenario_id: NonEmptyIdentifier  # type: ignore[valid-type]
    scenario_version: PositiveInt
    seed: int
    entry_count: PositiveInt
    final_digest: SHA256Digest  # type: ignore[valid-type]
    started_at: datetime
    completed_at: datetime


# ---------------------------------------------------------------------------
# Replay report
# ---------------------------------------------------------------------------


ReplayOutcomeStatus = Literal["verified", "tampered", "diverged"]


class DivergenceRecord(ContractModel):
    """One divergence between a recorded run and a replayed run."""

    model_config = ConfigDict(extra="forbid")

    sequence: PositiveInt
    kind: Literal[
        "tool_status_mismatch",
        "tool_result_mismatch",
        "tool_error_mismatch",
        "missing_tool",
        "extra_tool",
    ]
    detail: NonEmptyIdentifier


class ReplayReport(ContractModel):
    """The output of replaying (or verifying) a recorded run."""

    model_config = ConfigDict(extra="forbid")

    recording_run_id: uuid.UUID
    mode: Literal["playback", "verification"]
    status: ReplayOutcomeStatus
    divergences: tuple[DivergenceRecord, ...] = Field(default_factory=tuple)
    final_digest: SHA256Digest  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Assertion outcome
# ---------------------------------------------------------------------------


class AssertionOutcome(ContractModel):
    """The outcome of evaluating a single assertion."""

    model_config = ConfigDict(extra="forbid")

    assertion_id: NonEmptyIdentifier
    passed: bool
    observed: dict[str, Any]
    reason: str | None = None


# ---------------------------------------------------------------------------
# Trajectory contracts (scripted driver)
# ---------------------------------------------------------------------------


class InvokeToolStep(ContractModel):
    """A trajectory step that invokes a tool."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["invoke_tool"] = "invoke_tool"
    step_id: NonEmptyIdentifier  # type: ignore[valid-type]
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ProduceFinalResponseStep(ContractModel):
    """A trajectory step that records a final agent response."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["produce_final_response"] = "produce_final_response"
    step_id: NonEmptyIdentifier  # type: ignore[valid-type]
    response: str = Field(min_length=1)


class RecordCheckpointStep(ContractModel):
    """A trajectory step that records a state checkpoint."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["record_checkpoint"] = "record_checkpoint"
    step_id: NonEmptyIdentifier  # type: ignore[valid-type]
    label: str = Field(min_length=1)


# Trajectory step union. Use a discriminator at validation time.
TrajectoryStep = InvokeToolStep | ProduceFinalResponseStep | RecordCheckpointStep


class ScriptedTrajectory(ContractModel):
    """A deterministic scripted trajectory used by the ScriptedAgentDriver.

    Scripted trajectories are deterministic test doubles for the evaluation
    infrastructure. They are NOT benchmark ground truth for future agent
    quality measurements.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=RECORDING_SCHEMA_VERSION, ge=1)
    trajectory_id: NonEmptyIdentifier  # type: ignore[valid-type]
    description: str = Field(min_length=1)
    steps: tuple[TrajectoryStep, ...]  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _non_empty_steps(self) -> ScriptedTrajectory:
        if not self.steps:
            raise ValueError("ScriptedTrajectory must have at least one step")
        return self


# Re-export key types so external callers can import a single module.
__all__ = [
    "RECORDING_SCHEMA_VERSION",
    "JournalEntry",
    "JournalEntryType",
    "RunRecording",
    "ReplayReport",
    "DivergenceRecord",
    "AssertionOutcome",
    "TrajectoryStep",
    "InvokeToolStep",
    "ProduceFinalResponseStep",
    "RecordCheckpointStep",
    "ScriptedTrajectory",
]

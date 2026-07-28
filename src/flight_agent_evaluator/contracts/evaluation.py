"""Assertion and evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field

from flight_agent_evaluator.contracts.base import (
    ContractModel,
    SchemaVersion,
)
from flight_agent_evaluator.contracts.booking import BookingState
from flight_agent_evaluator.contracts.common import (
    NonEmptyIdentifier,
    NonNegativeDuration,
    NonNegativeInt,
    PositiveInt,
    ToolName,
)

# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


class ToolCalledAssertion(ContractModel):
    assertion_type: Literal["tool_called"] = "tool_called"
    tool_name: ToolName  # type: ignore[valid-type]


class ToolNotCalledAssertion(ContractModel):
    assertion_type: Literal["tool_not_called"] = "tool_not_called"
    tool_name: ToolName  # type: ignore[valid-type]


class ToolCallCountAssertion(ContractModel):
    assertion_type: Literal["tool_call_count"] = "tool_call_count"
    tool_name: ToolName  # type: ignore[valid-type]
    minimum: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]
    maximum: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]


class EventCountAssertion(ContractModel):
    assertion_type: Literal["event_count"] = "event_count"
    event_type: str = Field(min_length=1)
    minimum: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]
    maximum: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]


class BookingStateAssertion(ContractModel):
    assertion_type: Literal["booking_state"] = "booking_state"
    booking_id: NonEmptyIdentifier  # type: ignore[valid-type]
    expected_state: BookingState


class ApprovalStateAssertion(ContractModel):
    assertion_type: Literal["approval_state"] = "approval_state"
    request_id: NonEmptyIdentifier  # type: ignore[valid-type]
    expected_state: Literal["pending", "granted", "denied", "expired"]


class NoDuplicateSideEffectAssertion(ContractModel):
    assertion_type: Literal["no_duplicate_side_effect"] = "no_duplicate_side_effect"
    tool_name: ToolName  # type: ignore[valid-type]


class ReplayDeterminismAssertion(ContractModel):
    assertion_type: Literal["replay_determinism"] = "replay_determinism"


class MaximumLatencyAssertion(ContractModel):
    assertion_type: Literal["maximum_latency"] = "maximum_latency"
    max_seconds: PositiveInt  # type: ignore[valid-type]


class ForbiddenMutationAssertion(ContractModel):
    assertion_type: Literal["forbidden_mutation"] = "forbidden_mutation"
    tool_name: ToolName  # type: ignore[valid-type]


Assertion = Annotated[
    ToolCalledAssertion
    | ToolNotCalledAssertion
    | ToolCallCountAssertion
    | EventCountAssertion
    | BookingStateAssertion
    | ApprovalStateAssertion
    | NoDuplicateSideEffectAssertion
    | ReplayDeterminismAssertion
    | MaximumLatencyAssertion
    | ForbiddenMutationAssertion,
    Discriminator("assertion_type"),
]


# ---------------------------------------------------------------------------
# Outcome and status
# ---------------------------------------------------------------------------

AssertionStatus = Literal["passed", "failed", "skipped", "inconclusive"]


class AssertionOutcome(ContractModel):
    assertion: Any  # type: ignore[valid-type]
    status: AssertionStatus
    observed: Any | None = None  # type: ignore[valid-type]
    message: str | None = None


# ---------------------------------------------------------------------------
# Failure categories
# ---------------------------------------------------------------------------

FailureCategory = Literal[
    "incorrect_tool",
    "invalid_arguments",
    "provider_handling_failure",
    "stale_data_use",
    "unverified_external_action",
    "missing_approval",
    "duplicate_side_effect",
    "false_success_claim",
    "task_incomplete",
    "unsafe_mutation",
    "replay_divergence",
    "infrastructure_failure",
    "unknown",
]


class FailureClassification(ContractModel):
    category: FailureCategory
    description: str | None = None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

EvaluationStatus = Literal["passed", "failed", "inconclusive"]


class EvaluationMetric(ContractModel):
    name: str = Field(min_length=1)
    value: float | int | str | bool


class EvaluationSummary(ContractModel):
    total: NonNegativeInt  # type: ignore[valid-type]
    passed: NonNegativeInt  # type: ignore[valid-type]
    failed: NonNegativeInt  # type: ignore[valid-type]
    skipped: NonNegativeInt  # type: ignore[valid-type]


class EvaluationResult(ContractModel):
    schema_version: SchemaVersion = SchemaVersion(major=1, minor=0, patch=0)  # type: ignore[valid-type]
    evaluation_id: NonEmptyIdentifier  # type: ignore[valid-type]
    scenario_id: NonEmptyIdentifier  # type: ignore[valid-type]
    run_id: NonEmptyIdentifier  # type: ignore[valid-type]
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: NonNegativeDuration | None = None  # type: ignore[valid-type]
    status: EvaluationStatus
    summary: EvaluationSummary  # type: ignore[valid-type]
    outcomes: tuple[AssertionOutcome, ...]  # type: ignore[valid-type]
    metrics: tuple[EvaluationMetric, ...] = Field(default_factory=tuple)  # type: ignore[valid-type]
    failure: FailureClassification | None = None

"""Deterministic fault specifications."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Discriminator, Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import (
    NonNegativeInt,
    ProviderName,
    ToolName,
)

# ---------------------------------------------------------------------------
# Activation rules
# ---------------------------------------------------------------------------


class ActivationRule(ContractModel):
    """A rule describing when a fault should activate."""

    kind: Literal["always", "after_n_calls", "on_match", "time_window"]
    call_index: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]
    match_substring: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


# ---------------------------------------------------------------------------
# Individual fault types
# ---------------------------------------------------------------------------


class TimeoutFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    timeout_seconds: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    fault_type: Literal["timeout"] = "timeout"


class RateLimitFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    retry_after_seconds: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    fault_type: Literal["rate_limit"] = "rate_limit"


class ProviderServerErrorFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    status_code: NonNegativeInt = Field(ge=100, lt=600)  # type: ignore[valid-type]
    fault_type: Literal["provider_server_error"] = "provider_server_error"


class MalformedResponseFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    description: str = Field(min_length=1)
    fault_type: Literal["malformed_response"] = "malformed_response"


class StaleResponseFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    staleness_seconds: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    fault_type: Literal["stale_response"] = "stale_response"


class ConflictingResponseFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    field_path: str
    fault_type: Literal["conflicting_response"] = "conflicting_response"


class DelayedResponseFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    delay_seconds: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    fault_type: Literal["delayed_response"] = "delayed_response"


class DuplicateEventFault(ContractModel):
    target_provider: ProviderName  # type: ignore[valid-type]
    target_tool: ToolName | None = None
    activation: ActivationRule  # type: ignore[valid-type]
    occurrence_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    duplication_count: NonNegativeInt = Field(ge=1)  # type: ignore[valid-type]
    fault_type: Literal["duplicate_event"] = "duplicate_event"


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

FaultSpec = Annotated[
    TimeoutFault
    | RateLimitFault
    | ProviderServerErrorFault
    | MalformedResponseFault
    | StaleResponseFault
    | ConflictingResponseFault
    | DelayedResponseFault
    | DuplicateEventFault,
    Discriminator("fault_type"),
]

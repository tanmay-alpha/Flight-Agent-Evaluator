"""Tool call and result contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import (
    NonEmptyIdentifier,
    NonNegativeInt,
    SHA256Digest,
    ToolName,
)

# ---------------------------------------------------------------------------
# Mutation classification
# ---------------------------------------------------------------------------

ToolMutationClass = Literal[
    "read_only",
    "simulated_mutation",
    "sensitive_simulated_mutation",
]


# ---------------------------------------------------------------------------
# Tool call
# ---------------------------------------------------------------------------


class ToolCall(ContractModel):
    """A single invocation of a tool by an agent.

    ``call_id`` MUST be set explicitly by the caller via a deterministic
    ID factory so that recordings remain reproducible across runs with
    the same seed. There is no ``default_factory`` — that would inject
    process-local entropy and break determinism.
    """

    call_id: uuid.UUID
    run_id: uuid.UUID = Field(description="ID of the enclosing agent run")
    tool_name: ToolName  # type: ignore[valid-type]
    arguments: dict[str, Any] = Field(description="Structured JSON arguments")  # type: ignore[valid-type]
    mutation_class: ToolMutationClass = "read_only"
    start_time: datetime
    timeout_seconds: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]
    idempotency_key: SHA256Digest | None = Field(default=None)  # type: ignore[valid-type]
    approval_request_id: NonEmptyIdentifier | None = Field(default=None)  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Tool error
# ---------------------------------------------------------------------------


class ToolError(ContractModel):
    """A typed failure from a tool call."""

    error_type: Literal[
        "timeout",
        "cancelled",
        "invalid_arguments",
        "provider_error",
        "internal_error",
    ]
    message: str = Field(min_length=1)
    retryable: bool = Field(default=False)
    details: dict[str, Any] = Field(default_factory=dict)  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Tool result
# ---------------------------------------------------------------------------

ToolResultStatus = Literal[
    "success",
    "failure",
    "timeout",
    "cancelled",
]


class ToolResult(ContractModel):
    """Outcome of a tool call.

    A failed call is NOT represented as a successful result containing
    error text — it is a distinct status with a typed ``ToolError``.

    ``end_time`` is required because the executor advances the run's
    deterministic virtual clock at the boundary of every call. There
    is no ``default_factory`` — wall-clock reads would break
    determinism guarantees.
    """

    call_id: uuid.UUID
    status: ToolResultStatus
    result: Any | None = Field(default=None)  # type: ignore[valid-type]
    error: ToolError | None = Field(default=None)  # type: ignore[valid-type]
    end_time: datetime
    duration_ms: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _validate_result(self) -> ToolResult:
        if self.status == "success" and self.error is not None:
            raise ValueError("successful result must not have an error")
        if self.status in ("failure", "timeout", "cancelled") and self.error is None:
            raise ValueError(f"{self.status} result must have a ToolError")
        return self

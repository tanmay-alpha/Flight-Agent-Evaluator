"""Trace and span contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import (
    NonNegativeDuration,
    UtcDateTime,
)

# ---------------------------------------------------------------------------
# Span kind and status
# ---------------------------------------------------------------------------

SpanKind = Literal[
    "internal",
    "server",
    "client",
    "producer",
    "consumer",
]

SpanStatus = Literal[
    "ok",
    "error",
    "unset",
]

RunStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
    "timeout",
]


# ---------------------------------------------------------------------------
# Trace span
# ---------------------------------------------------------------------------


class TraceSpan(ContractModel):
    """A single span within a trace.

    Designed to be compatible with future OpenTelemetry mapping without
    importing OpenTelemetry in Phase 1.
    """

    span_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    trace_id: uuid.UUID = Field(description="ID of the enclosing trace")
    parent_span_id: uuid.UUID | None = Field(default=None)
    name: str = Field(min_length=1, description="Span name")
    kind: SpanKind
    status: SpanStatus = "unset"
    start_time: datetime = Field(default_factory=UtcDateTime.now)
    end_time: datetime | None = Field(default=None)
    duration_ms: NonNegativeDuration | None = Field(default=None)  # type: ignore[valid-type]
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: tuple[dict[str, Any], ...] = Field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Agent run
# ---------------------------------------------------------------------------


class AgentRun(ContractModel):
    """Top-level record of a single agent execution."""

    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    status: RunStatus
    started_at: datetime = Field(default_factory=UtcDateTime.now)
    ended_at: datetime | None = Field(default=None)
    duration_ms: NonNegativeDuration | None = Field(default=None)  # type: ignore[valid-type]
    root_span_id: uuid.UUID | None = Field(default=None)
    error: str | None = Field(default=None)

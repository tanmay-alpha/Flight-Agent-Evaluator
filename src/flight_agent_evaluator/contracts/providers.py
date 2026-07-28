"""Provider health, quota, and conflict contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from flight_agent_evaluator.contracts.base import (
    ContractModel,
    RawPayloadReference,
)
from flight_agent_evaluator.contracts.common import (
    NonEmptyIdentifier,
    NonNegativeInt,
    PositiveInt,
    ProviderName,
    UtcDateTime,
)

# ---------------------------------------------------------------------------
# Provider capability
# ---------------------------------------------------------------------------

ProviderCapability = Literal[
    "flight_status",
    "flight_search",
    "health",
    "quota",
]


# ---------------------------------------------------------------------------
# Provider health
# ---------------------------------------------------------------------------

ProviderHealthState = Literal[
    "healthy",
    "degraded",
    "unavailable",
    "unknown",
]


class ProviderHealth(ContractModel):
    """Current health status of a provider."""

    provider_name: ProviderName  # type: ignore[valid-type]
    state: ProviderHealthState
    checked_at: datetime = Field(default_factory=UtcDateTime.now)
    latency_ms: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]
    message: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Provider quota
# ---------------------------------------------------------------------------


class ProviderQuota(ContractModel):
    """Usage quota for a provider."""

    provider_name: ProviderName  # type: ignore[valid-type]
    requests_used: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    requests_limit: PositiveInt | None = Field(default=None)  # type: ignore[valid-type]
    remaining: NonNegativeInt | None = Field(default=None)  # type: ignore[valid-type]
    reset_at: datetime | None = Field(default=None)  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Provider observation summary
# ---------------------------------------------------------------------------


class ProviderObservationSummary(ContractModel):
    """Summary of a provider's recent observations."""

    provider_name: ProviderName  # type: ignore[valid-type]
    observation_count: NonNegativeInt = Field(ge=0)  # type: ignore[valid-type]
    oldest_observation: datetime | None = Field(default=None)  # type: ignore[name-defined]
    newest_observation: datetime | None = Field(default=None)  # type: ignore[name-defined]
    raw_payload_reference: RawPayloadReference | None = Field(default=None)  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Provider field conflict
# ---------------------------------------------------------------------------


class ProviderFieldConflict(ContractModel):
    """A single field where multiple providers disagree."""

    field_path: str = Field(description="Dot-path to the conflicting field")
    sources: dict[str, Any] = Field(  # type: ignore[valid-type]
        description="Mapping of provider name → conflicting value",
    )
    observation_timestamps: dict[str, datetime] = Field(  # type: ignore[valid-type]
        description="Mapping of provider name → observation time",
    )
    requires_human_confirmation: bool = Field(default=False)
    resolution: Any | None = Field(default=None)  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Provider conflict
# ---------------------------------------------------------------------------


class ProviderConflict(ContractModel):
    """A collection of conflicting observations across providers."""

    conflict_id: NonEmptyIdentifier  # type: ignore[valid-type]
    detected_at: datetime  # type: ignore[name-defined]
    field_conflicts: tuple[ProviderFieldConflict, ...]  # type: ignore[valid-type]
    resolved: bool = Field(default=False)
    resolution_note: str | None = Field(default=None)

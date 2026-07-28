"""Reusable constrained types for aviation and agent contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel

# ---------------------------------------------------------------------------
# Aviation string codes
# ---------------------------------------------------------------------------

IATAAirportCode = Annotated[
    str,
    Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="IATA airport code (3 uppercase letters)",
    ),
]

ICAOAirportCode = Annotated[
    str,
    Field(
        min_length=4,
        max_length=4,
        pattern=r"^[A-Z0-9]{4}$",
        description="ICAO airport code (4 uppercase alphanumeric)",
    ),
]

IATAAirlineCode = Annotated[
    str,
    Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z0-9]{2}$",
        description="IATA airline code (2 uppercase alphanumeric)",
    ),
]

ISOCurrencyCode = Annotated[
    str,
    Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 currency code (3 uppercase letters)",
    ),
]

# ---------------------------------------------------------------------------
# General string codes
# ---------------------------------------------------------------------------

NonEmptyIdentifier = Annotated[
    str,
    Field(min_length=1, description="Non-empty identifier string"),
]

ProviderName = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Provider name (alphanumeric, underscore, hyphen)",
    ),
]

ToolName = Annotated[
    str,
    Field(min_length=1, description="Tool name"),
]

SHA256Digest = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex digest (lowercase)",
    ),
]

IANATimezoneName = Annotated[
    str,
    Field(description="IANA timezone name, e.g. 'America/New_York'"),
]

# ---------------------------------------------------------------------------
# Numeric types
# ---------------------------------------------------------------------------

NonNegativeInt = Annotated[
    int,
    Field(ge=0, description="Non-negative integer"),
]

PositiveInt = Annotated[
    int,
    Field(gt=0, description="Strictly positive integer"),
]

NonNegativeDuration = Annotated[
    int,
    Field(ge=0, description="Duration in seconds (non-negative)"),
]

# ---------------------------------------------------------------------------
# Validated models
# ---------------------------------------------------------------------------


class FlightNumber(ContractModel):
    """Flight number with its marketing airline code."""

    airline_code: IATAAirlineCode  # type: ignore[valid-type]
    number: str = Field(
        pattern=r"^\d{1,4}[A-Z]?$",
        description="Flight number (1-4 digits, optional suffix letter)",
    )

    def __str__(self) -> str:
        return f"{self.airline_code}{self.number}"


class UtcDateTime:
    """Utility ensuring a datetime is timezone-aware and in UTC."""

    @staticmethod
    def require(value: datetime) -> datetime:
        """Raise if *value* is naive; return the UTC-normalised value."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"DateTime must be timezone-aware, got {value!r}")
        return value.astimezone(UTC)

    @staticmethod
    def now() -> datetime:
        """Return the current time in UTC."""
        return datetime.now(tz=UTC)

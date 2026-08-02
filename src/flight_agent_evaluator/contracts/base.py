"""Base contracts shared across all public types."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# JSON-serialisable Any — runtime validator ensures contract fields hold only
# JSON-compatible values.  Pydantic v2 cannot resolve recursive type aliases at
# model class-creation time, so we use Any + validator instead of dict[str, T].
# ---------------------------------------------------------------------------


def _assert_json_serialisable(value: Any, field_name: str) -> None:
    """Raise ValueError if *value* is not JSON-serialisable."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, Decimal):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_json_serialisable(item, field_name)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"Field {field_name!r} contains a non-string dict key: {k!r}")
            _assert_json_serialisable(v, field_name)
        return
    raise ValueError(
        f"Field {field_name!r} contains a non-JSON-serialisable value: {type(value).__name__}"
    )


def json_serialisable_validator(value: Any, field_name: str = "value") -> Any:
    _assert_json_serialisable(value, field_name)
    return value


# ---------------------------------------------------------------------------
# ContractModel
# ---------------------------------------------------------------------------


class ContractModel(BaseModel):
    """Base model for all public contracts.

    Guarantees:

    - Unknown fields are rejected (``extra="forbid"``).
    - Instances are immutable after construction (``frozen=True``).
    - Default values are validated on construction (``validate_default=True``).
    - Serialisation produces JSON-compatible primitives.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


class SchemaVersion(ContractModel):
    """Semantic version identifier for contract schemas."""

    major: int = Field(ge=0)
    minor: int = Field(ge=0)
    patch: int = Field(ge=0)

    @field_validator("major", "minor", "patch", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> int:
        return int(value)

    @classmethod
    def from_string(cls, value: str) -> SchemaVersion:
        parts = value.split(".")
        if len(parts) != 3:
            raise ValueError(f"SchemaVersion must be 'major.minor.patch', got {value!r}")
        major_s, minor_s, patch_s = parts
        return cls(
            major=int(major_s),
            minor=int(minor_s),
            patch=int(patch_s),
        )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @model_validator(mode="before")
    @classmethod
    def _coerce_from_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls.from_string(value).model_dump()
        return value


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


class Money(ContractModel):
    """Monetary amount with an ISO currency code."""

    amount: Decimal = Field(
        ge=Decimal("0"),
        description="Non-negative monetary amount",
    )
    currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 currency code",
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid monetary amount: {value!r}") from exc

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, value: str) -> str:
        return value.upper()

    @field_serializer("amount")
    def _serialize_amount(self, value: Decimal) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Raw payload reference
# ---------------------------------------------------------------------------


class RawPayloadReference(ContractModel):
    """Reference to raw bytes that produced a contract instance."""

    uri: str = Field(description="Stable URI identifying the payload source")
    sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex digest (lowercase)",
    )
    content_type: str | None = Field(
        default=None,
        description="MIME type of the payload",
    )
    byte_length: int | None = Field(
        default=None,
        ge=0,
        description="Byte length if known",
    )


# ---------------------------------------------------------------------------
# Normalisation warning
# ---------------------------------------------------------------------------


class NormalisationWarning(ContractModel):
    """A non-fatal adjustment applied during normalisation of raw data."""

    field: str = Field(description="Field that was adjusted")
    original_value: Any = Field(description="Original raw value")
    normalised_value: Any = Field(description="Value after adjustment")
    reason: str = Field(description="Why the adjustment was made")


# ---------------------------------------------------------------------------
# Source metadata
# ---------------------------------------------------------------------------


class SourceMetadata(ContractModel):
    """Provenance metadata for an observation produced by a provider."""

    provider_name: str = Field(
        min_length=1,
        description="Name of the provider that produced this",
    )
    provider_mode: Literal["fixture", "live"] = Field(
        description="Whether data is synthetic or live",
    )
    source_observation_time: datetime = Field(
        description="When the source observed the data (UTC)",
    )
    local_receipt_time: datetime = Field(
        description="When the receiver obtained the data (UTC)",
    )
    source_timezone: str | None = Field(
        default=None,
        description="IANA timezone of the source (for local aviation times)",
    )
    raw_payload_reference: RawPayloadReference | None = Field(
        default=None,
        description="Reference to the raw bytes",
    )
    normalisation_warnings: tuple[NormalisationWarning, ...] = Field(
        default_factory=tuple,
        description="Adjustments applied during normalisation",
    )

    @field_validator("source_observation_time", "local_receipt_time")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"DateTime must be timezone-aware, got {value!r}")
        return value

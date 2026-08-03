"""Aviation domain contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from flight_agent_evaluator.contracts.base import (
    ContractModel,
    Money,
    SchemaVersion,
    SourceMetadata,
)

# ---------------------------------------------------------------------------
# Airport
# ---------------------------------------------------------------------------


class Airport(ContractModel):
    """An airport identified by its IATA and/or ICAO code."""

    iata_code: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="IATA airport code",
    )
    icao_code: str | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        pattern=r"^[A-Z0-9]{4}$",
        description="ICAO airport code",
    )
    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    country: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    timezone: str | None = Field(
        default=None,
        description="IANA timezone name",
    )


# ---------------------------------------------------------------------------
# Airline
# ---------------------------------------------------------------------------


class Airline(ContractModel):
    """An airline identified by IATA and/or ICAO code."""

    iata_code: str = Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z0-9]{2}$",
        description="IATA airline code",
    )
    icao_code: str | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        pattern=r"^[A-Z0-9]{4}$",
        description="ICAO airline code",
    )
    name: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Flight identity
# ---------------------------------------------------------------------------


class FlightIdentity(ContractModel):
    """Uniquely identifies a scheduled flight."""

    flight_number: str = Field(min_length=1)
    marketing_airline_iata: str = Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z0-9]{2}$",
    )
    operating_airline_iata: str = Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z0-9]{2}$",
    )
    is_codeshare: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Flight time
# ---------------------------------------------------------------------------


class FlightTime(ContractModel):
    """Scheduled, actual, and estimated times for a flight event."""

    scheduled: datetime = Field(description="Scheduled time (timezone-aware)")
    actual: datetime | None = Field(default=None)
    estimated: datetime | None = Field(default=None)
    delay_minutes: int | None = Field(default=None, ge=0)

    @field_validator("scheduled", "actual", "estimated")
    @classmethod
    def _require_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError(f"DateTime must be timezone-aware, got {value!r}")
        return value


# ---------------------------------------------------------------------------
# Operational status
# ---------------------------------------------------------------------------

FlightOperationalStatus = (
    str  # Literal["scheduled", "active", "delayed", "cancelled", "diverted", "landed", "unknown"]
)


# ---------------------------------------------------------------------------
# Flight status
# ---------------------------------------------------------------------------


class FlightStatus(ContractModel):
    """Current operational status of a flight."""

    operational_status: str = Field(min_length=1)
    delay_minutes: int | None = Field(default=None, ge=0)
    gate: str | None = Field(default=None)
    terminal: str | None = Field(default=None)
    remarks: str | None = Field(default=None)

    @field_validator("delay_minutes")
    @classmethod
    def _non_negative_delay(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError(f"Delay minutes cannot be negative, got {value}")
        return value


# ---------------------------------------------------------------------------
# Flight segment
# ---------------------------------------------------------------------------


class FlightSegment(ContractModel):
    """One leg of a flight journey."""

    origin_iata: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    destination_iata: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    flight_id: FlightIdentity  # type: ignore[valid-type]
    departure: FlightTime  # type: ignore[valid-type]
    arrival: FlightTime  # type: ignore[valid-type]
    aircraft_type: str | None = Field(default=None)
    cabin_class: str | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_segment(self) -> FlightSegment:
        if self.origin_iata == self.destination_iata:
            raise ValueError(f"Origin and destination cannot be identical: {self.origin_iata}")
        return self


# ---------------------------------------------------------------------------
# Flight status query
# ---------------------------------------------------------------------------


class FlightStatusQuery(ContractModel):
    """Query parameters for requesting flight status."""

    flight_identity: FlightIdentity | None = Field(default=None)
    flight_number: str | None = Field(default=None, min_length=1)
    origin_iata: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    destination_iata: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    query_date: datetime | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_query(self) -> FlightStatusQuery:
        has_identity = self.flight_identity is not None
        has_flight_number = self.flight_number is not None
        has_route = (
            self.origin_iata is not None
            and self.destination_iata is not None
            and self.query_date is not None
        )
        if not has_identity and not has_flight_number and not has_route:
            raise ValueError(
                "Query must provide flight_identity, flight_number, or "
                "origin_iata + destination_iata + query_date"
            )
        # Identity is the strongest signal; reject partial overlaps.
        if has_identity and (has_flight_number or has_route):
            raise ValueError(
                "When flight_identity is provided, do not also set flight_number or route fields"
            )
        if has_flight_number and has_route:
            raise ValueError("Provide either flight_number or route+query_date, not both")
        return self


# ---------------------------------------------------------------------------
# Flight status observation
# ---------------------------------------------------------------------------


class FlightStatusObservation(ContractModel):
    """A single observed flight status from a provider."""

    query: FlightStatusQuery  # type: ignore[valid-type]
    segment: FlightSegment  # type: ignore[valid-type]
    status: FlightStatus  # type: ignore[valid-type]
    source_metadata: SourceMetadata  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Cabin class
# ---------------------------------------------------------------------------

CabinClass = str  # Literal["economy", "premium_economy", "business", "first"]


# ---------------------------------------------------------------------------
# Flight search request
# ---------------------------------------------------------------------------


class FlightSearchRequest(ContractModel):
    """Request parameters for searching flights."""

    origin_iata: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    destination_iata: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    departure_date: datetime
    return_date: datetime | None = Field(default=None)
    cabin_class: str = Field(default="economy", min_length=1)
    adults: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def _validate_search(self) -> FlightSearchRequest:
        if self.origin_iata == self.destination_iata:
            raise ValueError(f"Origin and destination cannot be identical: {self.origin_iata}")
        if self.return_date is not None and self.return_date < self.departure_date:
            raise ValueError("Return date must be on or after departure date")
        return self


# ---------------------------------------------------------------------------
# Flight offer segment
# ---------------------------------------------------------------------------


class FlightOfferSegment(ContractModel):
    """One segment within a flight offer."""

    segment_index: int = Field(gt=0)
    flight_id: FlightIdentity  # type: ignore[valid-type]
    departure_airport: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    arrival_airport: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )
    departure_time: datetime
    arrival_time: datetime
    cabin_class: str = Field(default="economy")
    aircraft_type: str | None = None


# ---------------------------------------------------------------------------
# Flight offer
# ---------------------------------------------------------------------------


class FlightOffer(ContractModel):
    """A single flight offer from a provider."""

    offer_id: str = Field(min_length=1)
    airline_iata: str = Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z0-9]{2}$",
    )
    segments: tuple[FlightOfferSegment, ...]  # type: ignore[valid-type]
    total_price: Money  # type: ignore[valid-type]
    booking_class: str | None = None
    provider_name: str = Field(min_length=1, description="Provider that returned this offer")

    @model_validator(mode="after")
    def _validate_offer(self) -> FlightOffer:
        if not self.segments:
            raise ValueError("FlightOffer must have at least one segment")
        return self


# ---------------------------------------------------------------------------
# Flight search result
# ---------------------------------------------------------------------------


class FlightSearchResult(ContractModel):
    """Result of a flight search, preserving provider provenance."""

    schema_version: SchemaVersion = Field(
        default_factory=lambda: SchemaVersion(major=1, minor=0, patch=0)
    )  # type: ignore[valid-type]
    query: FlightSearchRequest  # type: ignore[valid-type]
    offers: tuple[FlightOffer, ...]  # type: ignore[valid-type]
    source_metadata: SourceMetadata  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _validate_result(self) -> FlightSearchResult:
        if not self.offers:
            raise ValueError("FlightSearchResult must have at least one offer")
        return self

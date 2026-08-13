"""Deterministic synthetic flight fixture provider."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flight_agent_evaluator.contracts.aviation import (
    Airport,
    FlightIdentity,
    FlightOffer,
    FlightOfferSegment,
    FlightSearchRequest,
    FlightSearchResult,
    FlightSegment,
    FlightStatus,
    FlightStatusObservation,
    FlightStatusQuery,
    FlightTime,
)
from flight_agent_evaluator.contracts.base import (
    Money,
    RawPayloadReference,
    SchemaVersion,
    SourceMetadata,
)
from flight_agent_evaluator.contracts.common import SHA256Digest
from flight_agent_evaluator.providers.errors import (
    ProviderDataNotFoundError,
    ProviderInvalidResponseError,
    ProviderUnavailableError,
)

# ---------------------------------------------------------------------------
# Constants — all fixed for determinism
# ---------------------------------------------------------------------------

PROVIDER_NAME: str = "synthetic-fixture"
SCHEMA_VERSION = SchemaVersion(major=1, minor=0, patch=0)
FIXED_OBSERVATION_TIME: datetime = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
FIXED_RECEIPT_TIME: datetime = datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)
FIXTURE_URI_PREFIX: str = "fixture://flight_agent_evaluator/resources/fixtures/"

# Known synthetic fixtures and their identities.
KNOWN_FLIGHT_STATUS_FIXTURES: dict[str, dict[str, str]] = {
    "AS142": {"carrier": "AS", "date": "2026-07-28", "origin": "JFK", "destination": "LHR"},
}
KNOWN_SEARCH_FIXTURES: dict[str, dict[str, str]] = {
    "JFK-LAX-2026-07-28": {"origin": "JFK", "destination": "LAX", "date": "2026-07-28"},
    "JFK-LHR-2026-07-28": {"origin": "JFK", "destination": "LHR", "date": "2026-07-28"},
}

# ---------------------------------------------------------------------------
# Strict wire schemas — typed validation boundary
# ---------------------------------------------------------------------------


class _WireAirport(BaseModel):
    """Strict wire model for an airport in fixture JSON."""

    model_config = ConfigDict(extra="forbid")

    iata_code: str
    icao_code: str | None = None
    name: str
    city: str
    country: str
    timezone: str | None = None


class _WireAirline(BaseModel):
    """Strict wire model for airline identity."""

    model_config = ConfigDict(extra="forbid")

    iata_code: str
    name: str


class _WireFlightIdentity(BaseModel):
    """Strict wire model for flight identity."""

    model_config = ConfigDict(extra="forbid")

    flight_number: str
    marketing_airline_iata: str
    operating_airline_iata: str
    is_codeshare: bool = False


class _WireFlightTime(BaseModel):
    """Strict wire model for flight times."""

    model_config = ConfigDict(extra="forbid")

    scheduled: str | None = None
    estimated: str | None = None
    actual: str | None = None
    delay_minutes: int | None = None


class _WireFlightStatus(BaseModel):
    """Strict wire model for flight status."""

    model_config = ConfigDict(extra="forbid")

    operational_status: str
    delay_minutes: int | None = None
    gate: str | None = None
    terminal: str | None = None
    remarks: str | None = None


class _WireFlightSegment(BaseModel):
    """Strict wire model for a flight segment."""

    model_config = ConfigDict(extra="forbid")

    origin: _WireAirport
    destination: _WireAirport
    flight_identity: _WireFlightIdentity
    departure: _WireFlightTime
    arrival: _WireFlightTime
    aircraft_type: str | None = None
    cabin_class: str | None = None


class _WireFlightStatusPayload(BaseModel):
    """Strict wire model for the full flight-status fixture payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    fixture_name: str
    synthetic: bool
    provider_name: str
    source_observation_time: str
    local_receipt_time: str
    source_timezone: str
    query: dict[str, str]
    flight_identity: _WireFlightIdentity
    origin: _WireAirport
    destination: _WireAirport
    departure: _WireFlightTime
    arrival: _WireFlightTime
    status: _WireFlightStatus
    aircraft_type: str | None = None


class _WireFlightOfferSegment(BaseModel):
    """Strict wire model for a flight offer segment."""

    model_config = ConfigDict(extra="forbid")

    segment_index: int = Field(gt=0)
    flight_id: _WireFlightIdentity
    departure_airport: str
    arrival_airport: str
    departure_time: str
    arrival_time: str
    cabin_class: str = "economy"
    aircraft_type: str | None = None


class _WireFlightOffer(BaseModel):
    """Strict wire model for a flight offer."""

    model_config = ConfigDict(extra="forbid")

    offer_id: str
    airline_iata: str
    segments: list[_WireFlightOfferSegment]
    total_price: dict[str, Any]
    booking_class: str | None = None


class _WireFlightSearchPayload(BaseModel):
    """Strict wire model for the full flight-search fixture payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    fixture_name: str
    synthetic: bool
    provider_name: str
    source_observation_time: str
    local_receipt_time: str
    source_timezone: str
    query: dict[str, str]
    offers: list[_WireFlightOffer]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> SHA256Digest:
    return hashlib.sha256(data).hexdigest()


def _payload_ref(fixture_path: str, raw_bytes: bytes) -> RawPayloadReference:
    return RawPayloadReference(
        uri=f"{FIXTURE_URI_PREFIX}{fixture_path}",
        sha256=_sha256(raw_bytes),
        content_type="application/json",
        byte_length=len(raw_bytes),
    )


def _source_metadata(fixture_path: str, raw_bytes: bytes) -> SourceMetadata:
    return SourceMetadata(
        provider_name=PROVIDER_NAME,
        provider_mode="fixture",
        source_observation_time=FIXED_OBSERVATION_TIME,
        local_receipt_time=FIXED_RECEIPT_TIME,
        source_timezone="UTC",
        raw_payload_reference=_payload_ref(fixture_path, raw_bytes),
        normalisation_warnings=(),
    )


def _load_fixture(fixture_name: str) -> tuple[bytes, dict[str, Any]]:
    """Load a fixture JSON from package resources.

    Only allow-listed fixture names are accepted to prevent path traversal.
    Returns raw bytes and parsed JSON.
    """
    allowed = {"flight_status_delayed.json", "alternative_flights.json"}
    if fixture_name not in allowed:
        raise ProviderDataNotFoundError(
            provider=PROVIDER_NAME,
            safe_message=f"Unknown fixture: {fixture_name}",
        )
    resource = files("flight_agent_evaluator.resources.fixtures").joinpath(fixture_name)
    raw_bytes = resource.read_bytes()
    try:
        parsed = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ProviderInvalidResponseError(
            provider=PROVIDER_NAME,
            safe_message=f"Malformed fixture JSON: {fixture_name}",
        ) from exc
    return raw_bytes, parsed


def _parse_airport(data: _WireAirport) -> Airport:
    return Airport(
        iata_code=data.iata_code,
        icao_code=data.icao_code,
        name=data.name,
        city=data.city,
        country=data.country,
        timezone=data.timezone,
    )


def _parse_identity(data: _WireFlightIdentity) -> FlightIdentity:
    return FlightIdentity(
        flight_number=data.flight_number,
        marketing_airline_iata=data.marketing_airline_iata,
        operating_airline_iata=data.operating_airline_iata,
        is_codeshare=data.is_codeshare,
    )


def _parse_time(data: _WireFlightTime) -> FlightTime:
    def _dt(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)

    return FlightTime(
        scheduled=_dt(data.scheduled),
        estimated=_dt(data.estimated),
        actual=_dt(data.actual),
        delay_minutes=data.delay_minutes,
    )


def _parse_status(data: _WireFlightStatus) -> FlightStatus:
    return FlightStatus(
        operational_status=data.operational_status,
        delay_minutes=data.delay_minutes,
        gate=data.gate,
        terminal=data.terminal,
        remarks=data.remarks,
    )


def _parse_segment(data: _WireFlightSegment) -> FlightSegment:
    return FlightSegment(
        origin_iata=data.origin.iata_code,
        destination_iata=data.destination.iata_code,
        flight_id=_parse_identity(data.flight_identity),
        departure=_parse_time(data.departure),
        arrival=_parse_time(data.arrival),
        aircraft_type=data.aircraft_type,
        cabin_class=data.cabin_class,
    )


# ---------------------------------------------------------------------------
# FixtureFlightProvider
# ---------------------------------------------------------------------------


class FixtureFlightProvider:
    """Deterministic, network-free flight data provider.

    All data is loaded from packaged JSON fixtures via importlib.resources.
    No API key is required, no network calls are made, and all returned
    observations carry fixed timestamps and deterministic provenance.

    All methods are async to conform to the FlightProvider protocol.
    """

    # ------------------------------------------------------------------
    # FlightProvider protocol properties
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ("flight_status", "flight_search", "health", "quota")

    # ------------------------------------------------------------------
    # Provider health
    # ------------------------------------------------------------------

    async def health(self) -> Any:
        """Return fixed healthy status — no wall-clock dependency."""
        from flight_agent_evaluator.contracts.providers import ProviderHealth

        return ProviderHealth(
            provider_name=PROVIDER_NAME,
            state="healthy",
            checked_at=FIXED_OBSERVATION_TIME,
            message="Fixture provider is healthy",
        )

    async def quota(self) -> Any:
        """Return fixed quota info."""
        from flight_agent_evaluator.contracts.providers import ProviderQuota

        return ProviderQuota(
            provider_name=PROVIDER_NAME,
            requests_used=0,
            requests_limit=None,
            remaining=None,
        )

    # ------------------------------------------------------------------
    # Flight status
    # ------------------------------------------------------------------

    async def get_flight_status(
        self,
        query: FlightStatusQuery,
    ) -> FlightStatusObservation:
        """Return a deterministic flight status observation.

        Raises ProviderDataNotFoundError if the query does not match a known
        synthetic fixture.
        """
        # Resolve effective flight number from query.
        if query.flight_identity is not None:
            effective_fn: str = query.flight_identity.flight_number
        else:
            effective_fn = query.flight_number or ""

        if effective_fn is None:
            raise ProviderDataNotFoundError(
                provider=PROVIDER_NAME,
                safe_message="Cannot resolve flight number from query",
            )

        # Strict lookup: match by flight number.
        fixture_key = "AS142"
        fixture_identity = KNOWN_FLIGHT_STATUS_FIXTURES.get(fixture_key)
        if fixture_identity is None:
            raise ProviderUnavailableError(
                provider=PROVIDER_NAME,
                safe_message="Flight status fixture unavailable",
            )

        # Check flight number matches.
        if effective_fn != fixture_key:
            raise ProviderDataNotFoundError(
                provider=PROVIDER_NAME,
                safe_message=f"No fixture for flight {effective_fn!r}",
            )

        # Check date matches if provided.
        if query.query_date is not None:
            query_date_str = query.query_date.strftime("%Y-%m-%d")
            if query_date_str != fixture_identity["date"]:
                raise ProviderDataNotFoundError(
                    provider=PROVIDER_NAME,
                    safe_message=f"No fixture for AS142 on {query_date_str}",
                )

        # Check route if origin/destination provided.
        if query.origin_iata is not None and query.origin_iata != fixture_identity["origin"]:
            raise ProviderDataNotFoundError(
                provider=PROVIDER_NAME,
                safe_message=f"No fixture for AS142 from {query.origin_iata}",
            )
        if (
            query.destination_iata is not None
            and query.destination_iata != fixture_identity["destination"]
        ):
            raise ProviderDataNotFoundError(
                provider=PROVIDER_NAME,
                safe_message=f"No fixture for AS142 to {query.destination_iata}",
            )

        # Load fixture and validate against strict wire model.
        raw_bytes, raw = _load_fixture("flight_status_delayed.json")
        try:
            wire = _WireFlightStatusPayload.model_validate(raw)
        except Exception as exc:
            raise ProviderInvalidResponseError(
                provider=PROVIDER_NAME,
                safe_message="Malformed flight-status fixture",
            ) from exc

        origin = _parse_airport(wire.origin)
        destination = _parse_airport(wire.destination)
        identity = _parse_identity(wire.flight_identity)

        segment = FlightSegment(
            origin_iata=origin.iata_code,
            destination_iata=destination.iata_code,
            flight_id=identity,
            departure=_parse_time(wire.departure),
            arrival=_parse_time(wire.arrival),
            aircraft_type=wire.aircraft_type,
        )

        status = _parse_status(wire.status)

        source_meta = _source_metadata("flight_status_delayed.json", raw_bytes)

        return FlightStatusObservation(
            query=query,
            segment=segment,
            status=status,
            source_metadata=source_meta,
        )

    # ------------------------------------------------------------------
    # Flight search
    # ------------------------------------------------------------------

    async def search_flights(
        self,
        request: FlightSearchRequest,
    ) -> FlightSearchResult:
        """Return a deterministic flight search result.

        Raises ProviderDataNotFoundError for unsupported route/date combos.
        """
        raw_bytes, raw = _load_fixture("alternative_flights.json")

        # Strict lookup: validate route + date.
        search_key = f"{request.origin_iata}-{request.destination_iata}-{request.departure_date.strftime('%Y-%m-%d')}"
        known = KNOWN_SEARCH_FIXTURES.get(search_key)
        if known is None:
            raise ProviderDataNotFoundError(
                provider=PROVIDER_NAME,
                safe_message=(
                    f"No fixture for route "
                    f"{request.origin_iata}->{request.destination_iata} "
                    f"on {request.departure_date.strftime('%Y-%m-%d')}"
                ),
            )

        # Parse via strict wire model.
        try:
            wire = _WireFlightSearchPayload.model_validate(raw)
        except Exception as exc:
            raise ProviderInvalidResponseError(
                provider=PROVIDER_NAME,
                safe_message="Malformed flight-search fixture",
            ) from exc

        def _seg(seg_data: _WireFlightOfferSegment) -> FlightOfferSegment:
            return FlightOfferSegment(
                segment_index=seg_data.segment_index,
                flight_id=_parse_identity(seg_data.flight_id),
                departure_airport=seg_data.departure_airport,
                arrival_airport=seg_data.arrival_airport,
                departure_time=datetime.fromisoformat(seg_data.departure_time),
                arrival_time=datetime.fromisoformat(seg_data.arrival_time),
                cabin_class=seg_data.cabin_class,
                aircraft_type=seg_data.aircraft_type,
            )

        offers = []
        for offer_data in wire.offers:
            segments = tuple(
                _seg(s) for s in sorted(offer_data.segments, key=lambda s: s.segment_index)
            )
            offers.append(
                FlightOffer(
                    offer_id=offer_data.offer_id,
                    airline_iata=offer_data.airline_iata,
                    segments=segments,
                    total_price=Money(
                        amount=offer_data.total_price["amount"],
                        currency=offer_data.total_price["currency"],
                    ),
                    booking_class=offer_data.booking_class,
                    provider_name=PROVIDER_NAME,
                )
            )

        # Deterministic ordering by offer_id.
        offers.sort(key=lambda o: o.offer_id)

        source_meta = _source_metadata("alternative_flights.json", raw_bytes)

        return FlightSearchResult(
            schema_version=SCHEMA_VERSION,
            query=request,
            offers=tuple(offers),
            source_metadata=source_meta,
        )

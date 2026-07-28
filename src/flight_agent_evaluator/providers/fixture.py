"""Deterministic synthetic flight fixture provider."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from importlib.resources import files
from typing import Any

from flight_agent_evaluator.contracts.aviation import (
    Airline,
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
from flight_agent_evaluator.contracts.common import (
    SHA256Digest,
    UtcDateTime,
)
from flight_agent_evaluator.contracts.providers import (
    ProviderCapability,
    ProviderHealth,
    ProviderQuota,
)
from flight_agent_evaluator.providers.errors import (
    ProviderDataNotFoundError as ProviderDataNotFoundErrorType,
    ProviderUnavailableError as ProviderUnavailableErrorType,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROVIDER_NAME: str = "synthetic-fixture"
SCHEMA_VERSION = SchemaVersion(major=1, minor=0, patch=0)
SOURCE_OBSERVATION_TIME: datetime = datetime.fromisoformat("2026-07-28T10:00:00+00:00")
LOCAL_RECEIPT_TIME: datetime = datetime.fromisoformat("2026-07-28T10:00:00+00:00")
FIXTURE_URI_PREFIX: str = "fixture://flight_agent_evaluator/resources/fixtures/"

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
        source_observation_time=SOURCE_OBSERVATION_TIME,
        local_receipt_time=LOCAL_RECEIPT_TIME,
        source_timezone="UTC",
        raw_payload_reference=_payload_ref(fixture_path, raw_bytes),
        normalisation_warnings=(),
    )


def _load_fixture(fixture_name: str) -> tuple[dict[str, Any], bytes]:
    """Load a fixture JSON from package resources.

    Only allow-listed fixture names are accepted to prevent path traversal.
    """
    allowed = {"flight_status_delayed.json", "alternative_flights.json"}
    if fixture_name not in allowed:
        raise ProviderDataNotFoundErrorType(
            provider=PROVIDER_NAME,
            safe_message=f"Unknown fixture: {fixture_name}",
        )
    resource = files("flight_agent_evaluator.resources.fixtures").joinpath(fixture_name)
    raw_bytes = resource.read_bytes()
    return json.loads(raw_bytes), raw_bytes


def _parse_airport(data: dict[str, Any]) -> Airport:
    return Airport(
        iata_code=data["iata_code"],
        icao_code=data.get("icao_code"),
        name=data["name"],
        city=data["city"],
        country=data["country"],
        timezone=data.get("timezone"),
    )


def _parse_airline(iata_code: str, name: str) -> Airline:
    return Airline(iata_code=iata_code, name=name)


def _parse_identity(data: dict[str, Any]) -> FlightIdentity:
    return FlightIdentity(
        flight_number=data["flight_number"],
        marketing_airline_iata=data["marketing_airline_iata"],
        operating_airline_iata=data["operating_airline_iata"],
        is_codeshare=data.get("is_codeshare", False),
    )


def _parse_time(data: dict[str, Any]) -> FlightTime:
    def _dt(value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)

    return FlightTime(
        scheduled=_dt(data["scheduled"]),
        estimated=_dt(data.get("estimated")),
        actual=_dt(data.get("actual")),
        delay_minutes=data.get("delay_minutes"),
    )


def _parse_status(data: dict[str, Any]) -> FlightStatus:
    return FlightStatus(
        operational_status=data["operational_status"],
        delay_minutes=data.get("delay_minutes"),
        gate=data.get("gate"),
        terminal=data.get("terminal"),
        remarks=data.get("remarks"),
    )


def _parse_segment(data: dict[str, Any]) -> FlightSegment:
    return FlightSegment(
        origin_iata=data["origin"]["iata_code"],
        destination_iata=data["destination"]["iata_code"],
        flight_id=_parse_identity(data["flight_identity"]),
        departure=_parse_time(data["departure"]),
        arrival=_parse_time(data["arrival"]),
        aircraft_type=data.get("aircraft_type"),
        cabin_class=data.get("cabin_class"),
    )


# ---------------------------------------------------------------------------
# FixtureFlightProvider
# ---------------------------------------------------------------------------


class FixtureFlightProvider:
    """Deterministic, network-free flight data provider.

    All data is loaded from packaged JSON fixtures via importlib.resources.
    No API key is required, no network calls are made, and all returned
    observations carry fixed timestamps and deterministic provenance.
    """

    def __init__(self) -> None:
        pass  # No mutable shared state — provider is stateless and safe for parallel use.

    # ------------------------------------------------------------------
    # FlightProvider protocol properties
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return ("flight_status", "flight_search", "health", "quota")

    # ------------------------------------------------------------------
    # Provider health
    # ------------------------------------------------------------------

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=PROVIDER_NAME,
            state="healthy",
            checked_at=UtcDateTime.now(),
            message="Fixture provider is healthy",
        )

    def quota(self) -> ProviderQuota:
        return ProviderQuota(
            provider_name=PROVIDER_NAME,
            requests_used=0,
            requests_limit=None,
            remaining=None,
        )

    # ------------------------------------------------------------------
    # Flight status
    # ------------------------------------------------------------------

    def get_flight_status(
        self,
        query: FlightStatusQuery,
    ) -> FlightStatusObservation:
        try:
            raw, raw_bytes = _load_fixture("flight_status_delayed.json")
        except ProviderDataNotFoundErrorType as err:
            raise ProviderUnavailableErrorType(
                provider=PROVIDER_NAME,
                safe_message="Fixture unavailable",
            ) from err

        origin = _parse_airport(raw["origin"])
        destination = _parse_airport(raw["destination"])
        identity = _parse_identity(raw["flight_identity"])

        segment = FlightSegment(
            origin_iata=origin.iata_code,
            destination_iata=destination.iata_code,
            flight_id=identity,
            departure=_parse_time(raw["departure"]),
            arrival=_parse_time(raw["arrival"]),
            aircraft_type=raw.get("aircraft_type"),
        )

        status = _parse_status(raw["status"])

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

    def search_flights(
        self,
        request: FlightSearchRequest,
    ) -> FlightSearchResult:
        try:
            raw, raw_bytes = _load_fixture("alternative_flights.json")
        except ProviderDataNotFoundErrorType as err:
            raise ProviderUnavailableErrorType(
                provider=PROVIDER_NAME,
                safe_message="Fixture unavailable",
            ) from err

        def _seg(seg_data: dict[str, Any]) -> FlightOfferSegment:
            return FlightOfferSegment(
                segment_index=seg_data["segment_index"],
                flight_id=_parse_identity(seg_data["flight_id"]),
                departure_airport=seg_data["departure_airport"],
                arrival_airport=seg_data["arrival_airport"],
                departure_time=datetime.fromisoformat(seg_data["departure_time"]),
                arrival_time=datetime.fromisoformat(seg_data["arrival_time"]),
                cabin_class=seg_data.get("cabin_class", "economy"),
                aircraft_type=seg_data.get("aircraft_type"),
            )

        offers = []
        for offer_data in raw["offers"]:
            segments = tuple(
                _seg(s)
                for s in sorted(
                    offer_data["segments"],
                    key=lambda s: s["segment_index"],
                )
            )
            offers.append(
                FlightOffer(
                    offer_id=offer_data["offer_id"],
                    airline_iata=offer_data["airline_iata"],
                    segments=segments,
                    total_price=Money(
                        amount=offer_data["total_price"]["amount"],
                        currency=offer_data["total_price"]["currency"],
                    ),
                    booking_class=offer_data.get("booking_class"),
                    provider_name=PROVIDER_NAME,
                )
            )

        # Deterministic ordering by offer_id (already sorted in JSON,
        # but we sort explicitly to be safe).
        offers.sort(key=lambda o: o.offer_id)

        source_meta = _source_metadata("alternative_flights.json", raw_bytes)

        return FlightSearchResult(
            schema_version=SCHEMA_VERSION,
            query=request,
            offers=tuple(offers),
            source_metadata=source_meta,
        )

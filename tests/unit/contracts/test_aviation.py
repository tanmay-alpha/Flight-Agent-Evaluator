"""Tests for aviation contract models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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
    SchemaVersion,
    SourceMetadata,
)


def _dt(hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def _airport() -> Airport:
    return Airport(iata_code="JFK", name="JFK", city="NY", country="US")


def _identity() -> FlightIdentity:
    return FlightIdentity(
        flight_number="AA1",
        marketing_airline_iata="AA",
        operating_airline_iata="AA",
    )


def _flight_time() -> FlightTime:
    return FlightTime(scheduled=_dt(hour=8))


def _flight_status() -> FlightStatus:
    return FlightStatus(operational_status="delayed", delay_minutes=30)


class TestAirport:
    def test_valid(self) -> None:
        a = _airport()
        assert a.iata_code == "JFK"

    def test_lowercase_iata_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Airport(iata_code="jfk", name="x", city="x", country="US")


class TestAirline:
    def test_valid(self) -> None:
        al = Airline(iata_code="AA", name="American")
        assert al.iata_code == "AA"


class TestFlightIdentity:
    def test_valid(self) -> None:
        fi = _identity()
        assert fi.flight_number == "AA1"
        assert fi.is_codeshare is False


class TestFlightStatusQuery:
    def test_valid_with_flight_number(self) -> None:
        q = FlightStatusQuery(flight_number="AA123")
        assert q.flight_number == "AA123"

    def test_valid_with_route(self) -> None:
        q = FlightStatusQuery(
            origin_iata="JFK",
            destination_iata="LAX",
            query_date=_dt(),
        )
        assert q.origin_iata == "JFK"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FlightStatusQuery()

    def test_identity_valid(self) -> None:
        q = FlightStatusQuery(
            flight_identity=_identity(),
        )
        assert q.flight_identity.flight_number == "AA1"


class TestFlightOffer:
    def _segment(self) -> FlightOfferSegment:
        return FlightOfferSegment(
            segment_index=1,
            flight_id=_identity(),
            departure_airport="JFK",
            arrival_airport="LAX",
            departure_time=_dt(hour=8),
            arrival_time=_dt(hour=11),
        )

    def test_valid(self) -> None:
        offer = FlightOffer(
            offer_id="O1",
            airline_iata="AA",
            segments=(self._segment(),),
            total_price=Money(amount=100, currency="USD"),
            provider_name="synthetic-fixture",
        )
        assert offer.offer_id == "O1"

    def test_empty_segments_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FlightOffer(
                offer_id="O1",
                airline_iata="AA",
                segments=(),
                total_price=Money(amount=0, currency="USD"),
                provider_name="synthetic-fixture",
            )


class TestFlightSearchResult:
    def _offer(self) -> FlightOffer:
        seg = FlightOfferSegment(
            segment_index=1,
            flight_id=_identity(),
            departure_airport="JFK",
            arrival_airport="LAX",
            departure_time=_dt(hour=8),
            arrival_time=_dt(hour=11),
        )
        return FlightOffer(
            offer_id="O1",
            airline_iata="AA",
            segments=(seg,),
            total_price=Money(amount=100, currency="USD"),
            provider_name="synthetic-fixture",
        )

    def test_valid(self) -> None:
        r = FlightSearchResult(
            schema_version=SchemaVersion(major=1, minor=0, patch=0),
            query=FlightSearchRequest(
                origin_iata="JFK",
                destination_iata="LAX",
                departure_date=_dt(),
            ),
            offers=(self._offer(),),
            source_metadata=SourceMetadata(
                provider_name="synthetic-fixture",
                provider_mode="fixture",
                source_observation_time=_dt(),
                local_receipt_time=_dt(),
            ),
        )
        assert len(r.offers) == 1

    def test_empty_offers_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FlightSearchResult(
                schema_version=SchemaVersion(major=1, minor=0, patch=0),
                query=FlightSearchRequest(
                    origin_iata="JFK",
                    destination_iata="LAX",
                    departure_date=_dt(),
                ),
                offers=(),
                source_metadata=SourceMetadata(
                    provider_name="synthetic-fixture",
                    provider_mode="fixture",
                    source_observation_time=_dt(),
                    local_receipt_time=_dt(),
                ),
            )


class TestFlightSegment:
    def test_valid(self) -> None:
        s = FlightSegment(
            origin_iata="JFK",
            destination_iata="LAX",
            flight_id=_identity(),
            departure=_flight_time(),
            arrival=_flight_time(),
        )
        assert s.origin_iata == "JFK"


class TestFlightStatusObservation:
    def test_valid(self) -> None:
        seg = FlightSegment(
            origin_iata="JFK",
            destination_iata="LAX",
            flight_id=_identity(),
            departure=_flight_time(),
            arrival=_flight_time(),
        )
        obs = FlightStatusObservation(
            query=FlightStatusQuery(flight_number="AA1"),
            segment=seg,
            status=_flight_status(),
            source_metadata=SourceMetadata(
                provider_name="x",
                provider_mode="fixture",
                source_observation_time=_dt(),
                local_receipt_time=_dt(),
            ),
        )
        assert obs.status.operational_status == "delayed"

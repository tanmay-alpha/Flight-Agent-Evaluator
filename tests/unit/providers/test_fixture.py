"""Tests for the deterministic fixture provider."""

from __future__ import annotations

from datetime import UTC, datetime

from flight_agent_evaluator.contracts.aviation import FlightSearchRequest, FlightStatusQuery
from flight_agent_evaluator.providers.fixture import PROVIDER_NAME, FixtureFlightProvider


class TestFixtureFlightProviderBasics:
    def test_provider_name(self) -> None:
        p = FixtureFlightProvider()
        assert p.provider_name == PROVIDER_NAME
        assert PROVIDER_NAME == "synthetic-fixture"

    def test_capabilities(self) -> None:
        p = FixtureFlightProvider()
        caps = p.capabilities
        assert "flight_status" in caps
        assert "flight_search" in caps
        assert "health" in caps
        assert "quota" in caps

    def test_health(self) -> None:
        p = FixtureFlightProvider()
        h = p.health()
        assert h.provider_name == PROVIDER_NAME
        assert h.state == "healthy"

    def test_quota(self) -> None:
        p = FixtureFlightProvider()
        q = p.quota()
        assert q.provider_name == PROVIDER_NAME
        assert q.requests_used == 0


class TestFixtureFlightProviderDeterminism:
    """Same input yields byte-identical output (modulo captured_at timestamps)."""

    def test_status_query_deterministic(self) -> None:
        p1 = FixtureFlightProvider()
        p2 = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        r1 = p1.get_flight_status(q)
        r2 = p2.get_flight_status(q)
        # Compare core fields; provenance is deterministic by design.
        assert r1.segment.flight_id.flight_number == r2.segment.flight_id.flight_number
        assert r1.status.operational_status == r2.status.operational_status
        assert r1.source_metadata.provider_name == r2.source_metadata.provider_name

    def test_search_request_deterministic(self) -> None:
        p1 = FixtureFlightProvider()
        p2 = FixtureFlightProvider()
        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="LAX",
            departure_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        r1 = p1.search_flights(req)
        r2 = p2.search_flights(req)
        assert len(r1.offers) == len(r2.offers)
        for o1, o2 in zip(r1.offers, r2.offers, strict=True):
            assert o1.offer_id == o2.offer_id
            assert o1.total_price.amount == o2.total_price.amount


class TestFixtureFlightProviderStatus:
    def test_returns_observation(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AA1")
        obs = p.get_flight_status(q)
        assert obs.segment.origin_iata != obs.segment.destination_iata
        assert obs.source_metadata.provider_name == PROVIDER_NAME


class TestFixtureFlightProviderSearch:
    def test_returns_offers(self) -> None:
        p = FixtureFlightProvider()
        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="LAX",
            departure_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        res = p.search_flights(req)
        assert res.offers, "fixture must have at least one offer"
        for offer in res.offers:
            assert offer.provider_name == PROVIDER_NAME
            assert offer.total_price.currency == "USD"

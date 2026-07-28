"""Tests for FlightProvider protocol conformance (async)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from flight_agent_evaluator.contracts.aviation import FlightSearchRequest, FlightStatusQuery
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider


class TestFlightProviderProtocol:
    """FixtureFlightProvider must conform structurally and statically to FlightProvider."""

    def test_isinstance_flight_provider(self) -> None:
        assert isinstance(FixtureFlightProvider(), FlightProvider)

    def test_health_is_coroutine_function(self) -> None:
        p = FixtureFlightProvider()
        assert asyncio.iscoroutinefunction(p.health)

    def test_get_flight_status_is_coroutine_function(self) -> None:
        p = FixtureFlightProvider()
        assert asyncio.iscoroutinefunction(p.get_flight_status)

    def test_search_flights_is_coroutine_function(self) -> None:
        p = FixtureFlightProvider()
        assert asyncio.iscoroutinefunction(p.search_flights)

    def test_await_health(self) -> None:
        result = asyncio.run(FixtureFlightProvider().health())
        assert result.provider_name == "synthetic-fixture"
        assert result.state == "healthy"

    def test_await_get_flight_status(self) -> None:
        q = FlightStatusQuery(flight_number="AS142")
        result = asyncio.run(FixtureFlightProvider().get_flight_status(q))
        assert result.segment.flight_id.flight_number == "AS142"

    def test_await_search_flights(self) -> None:
        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="LAX",
            departure_date=datetime(2026, 7, 28, tzinfo=UTC),
        )
        result = asyncio.run(FixtureFlightProvider().search_flights(req))
        assert len(result.offers) > 0

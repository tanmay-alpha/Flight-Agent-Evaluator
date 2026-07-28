"""Tests for the deterministic fixture provider."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from flight_agent_evaluator.contracts.aviation import FlightSearchRequest, FlightStatusQuery
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider


class TestFixtureFlightProviderBasics:
    def test_provider_name(self) -> None:
        p = FixtureFlightProvider()
        assert p.provider_name == "synthetic-fixture"

    def test_capabilities(self) -> None:
        p = FixtureFlightProvider()
        caps = p.capabilities
        assert "flight_status" in caps
        assert "flight_search" in caps
        assert "health" in caps
        assert "quota" in caps

    def test_no_init_side_effects(self) -> None:
        p1 = FixtureFlightProvider()
        p2 = FixtureFlightProvider()
        assert p1.provider_name == p2.provider_name


class TestFixtureFlightProviderDeterminism:
    """Identical inputs yield byte-identical output."""

    def test_status_byte_identical(self) -> None:
        import hashlib

        from flight_agent_evaluator.canonical import canonical_hash, canonical_json

        p1 = FixtureFlightProvider()
        p2 = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        r1 = asyncio.run(p1.get_flight_status(q))
        r2 = asyncio.run(p2.get_flight_status(q))
        assert r1 == r2
        assert r1.model_dump(mode="json") == r2.model_dump(mode="json")
        assert canonical_hash(r1.model_dump(mode="json")) == canonical_hash(
            r2.model_dump(mode="json")
        )
        h1 = hashlib.sha256(canonical_json(r1.model_dump(mode="json")).encode("utf-8")).hexdigest()
        h2 = hashlib.sha256(canonical_json(r2.model_dump(mode="json")).encode("utf-8")).hexdigest()
        assert h1 == h2

    def test_search_byte_identical(self) -> None:
        from flight_agent_evaluator.canonical import canonical_hash

        p1 = FixtureFlightProvider()
        p2 = FixtureFlightProvider()
        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="LAX",
            departure_date=datetime(2026, 7, 28, tzinfo=UTC),
        )
        r1 = asyncio.run(p1.search_flights(req))
        r2 = asyncio.run(p2.search_flights(req))
        assert r1 == r2
        assert r1.model_dump(mode="json") == r2.model_dump(mode="json")
        assert canonical_hash(r1.model_dump(mode="json")) == canonical_hash(
            r2.model_dump(mode="json")
        )

    def test_repeated_calls_stable(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        first = asyncio.run(p.get_flight_status(q))
        for _ in range(5):
            assert asyncio.run(p.get_flight_status(q)) == first

    def test_mutation_of_caller_value_does_not_affect_result(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        r1 = asyncio.run(p.get_flight_status(q))
        r2 = asyncio.run(p.get_flight_status(q))
        assert r1 == r2

    def test_no_wall_clock_in_output(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        obs = asyncio.run(p.get_flight_status(q))
        # Verify fixed timestamps are used (UTC ISO format, no `now()`).
        assert obs.source_metadata.source_observation_time == datetime(
            2026, 7, 28, 10, 0, 0, tzinfo=UTC
        )
        assert obs.source_metadata.local_receipt_time == datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)


class TestFixtureFlightProviderStatus:
    def test_returns_observation(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        obs = asyncio.run(p.get_flight_status(q))
        assert obs.segment.origin_iata == "JFK"
        assert obs.segment.destination_iata == "LHR"
        assert obs.source_metadata.provider_name == "synthetic-fixture"

    def test_unknown_flight_raises(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AA1")
        with pytest.raises(ProviderDataNotFoundError):
            asyncio.run(p.get_flight_status(q))

    def test_wrong_carrier_raises(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="DL999")
        with pytest.raises(ProviderDataNotFoundError):
            asyncio.run(p.get_flight_status(q))

    def test_wrong_date_raises(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        q = FlightStatusQuery(
            flight_number="AS142",
            query_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(ProviderDataNotFoundError):
            asyncio.run(p.get_flight_status(q))

    def test_wrong_origin_raises(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        q = FlightStatusQuery(
            flight_number="AS142",
            origin_iata="LAX",
        )
        with pytest.raises(ProviderDataNotFoundError):
            asyncio.run(p.get_flight_status(q))

    def test_wrong_destination_raises(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        q = FlightStatusQuery(
            flight_number="AS142",
            destination_iata="JFK",
        )
        with pytest.raises(ProviderDataNotFoundError):
            asyncio.run(p.get_flight_status(q))


class TestFixtureFlightProviderSearch:
    def test_returns_offers(self) -> None:
        p = FixtureFlightProvider()
        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="LAX",
            departure_date=datetime(2026, 7, 28, tzinfo=UTC),
        )
        res = asyncio.run(p.search_flights(req))
        assert len(res.offers) == 3
        for offer in res.offers:
            assert offer.provider_name == "synthetic-fixture"
            assert offer.total_price.currency == "USD"

    def test_unsupported_route_raises(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="CDG",
            departure_date=datetime(2026, 7, 28, tzinfo=UTC),
        )
        with pytest.raises(ProviderDataNotFoundError):
            asyncio.run(p.search_flights(req))

    def test_unsupported_date_raises(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="LAX",
            departure_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(ProviderDataNotFoundError):
            asyncio.run(p.search_flights(req))


class TestFixtureFlightProviderProvenance:
    def test_fixed_observation_timestamp(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        obs = asyncio.run(p.get_flight_status(q))
        assert obs.source_metadata.source_observation_time == datetime(
            2026, 7, 28, 10, 0, 0, tzinfo=UTC
        )
        assert obs.source_metadata.local_receipt_time == datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)

    def test_fixed_health_timestamp(self) -> None:
        p = FixtureFlightProvider()
        health = asyncio.run(p.health())
        assert health.checked_at == datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC)

    def test_raw_payload_sha256(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        obs = asyncio.run(p.get_flight_status(q))
        ref = obs.source_metadata.raw_payload_reference
        assert ref is not None
        assert len(ref.sha256) == 64
        assert all(c in "0123456789abcdef" for c in ref.sha256)

    def test_raw_payload_byte_length(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        obs = asyncio.run(p.get_flight_status(q))
        ref = obs.source_metadata.raw_payload_reference
        assert ref is not None
        assert ref.byte_length is not None
        assert ref.byte_length > 0

    def test_fixture_uri_format(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        obs = asyncio.run(p.get_flight_status(q))
        ref = obs.source_metadata.raw_payload_reference
        assert ref is not None
        assert ref.uri.startswith("fixture://flight_agent_evaluator/resources/fixtures/")

    def test_content_type_set(self) -> None:
        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AS142")
        obs = asyncio.run(p.get_flight_status(q))
        ref = obs.source_metadata.raw_payload_reference
        assert ref is not None
        assert ref.content_type == "application/json"

    def test_no_credentials_required(self) -> None:
        # Provider must not require any env vars or credentials.
        import os

        FixtureFlightProvider()
        relevant = [k for k in os.environ if k.startswith(("API_", "TOKEN_", "KEY_"))]
        assert not relevant

    def test_unknown_fixture_name_rejected(self) -> None:
        """Direct fixture loading rejects unknown names (path traversal)."""
        from flight_agent_evaluator.providers import fixture as fx
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        with pytest.raises(ProviderDataNotFoundError):
            fx._load_fixture("../etc/passwd")

    def test_invalid_json_rejected(self) -> None:
        """Malformed fixture JSON raises ProviderInvalidResponseError, not raw ValidationError."""
        # Patch allowed list temporarily to inject bad JSON.
        # Type confusion with a bytes payload that fails JSON parsing.
        import unittest.mock as mock

        from flight_agent_evaluator.providers import fixture as fx
        from flight_agent_evaluator.providers.errors import ProviderInvalidResponseError

        with mock.patch("flight_agent_evaluator.providers.fixture.files") as mf:
            mock_resource = mock.Mock()
            mock_resource.read_bytes.return_value = b"{ not valid json"
            mf.return_value.joinpath.return_value = mock_resource
            with pytest.raises(ProviderInvalidResponseError):
                fx._load_fixture("flight_status_delayed.json")


class TestFixtureFlightProviderErrorMetadata:
    """Provider errors carry safe, non-leaking metadata."""

    def test_data_not_found_metadata(self) -> None:
        from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError

        p = FixtureFlightProvider()
        q = FlightStatusQuery(flight_number="AA1")
        try:
            asyncio.run(p.get_flight_status(q))
        except ProviderDataNotFoundError as exc:
            assert exc.error_code == "provider_data_not_found"
            assert exc.provider == "synthetic-fixture"
            assert exc.retryable is False
            assert exc.correlation_id
            assert exc.safe_message

    def test_invalid_response_does_not_leak_raw_payload(self) -> None:
        import unittest.mock as mock

        from flight_agent_evaluator.providers import fixture as fx
        from flight_agent_evaluator.providers.errors import ProviderInvalidResponseError

        with mock.patch("flight_agent_evaluator.providers.fixture.files") as mf:
            mock_resource = mock.Mock()
            mock_resource.read_bytes.return_value = b"{ not valid json"
            mf.return_value.joinpath.return_value = mock_resource
            try:
                fx._load_fixture("flight_status_delayed.json")
            except ProviderInvalidResponseError as exc:
                # safe_message must not contain raw JSON bytes.
                assert "{" not in exc.safe_message
                assert "not valid json" not in exc.safe_message

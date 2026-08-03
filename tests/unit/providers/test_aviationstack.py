"""Unit tests for AviationStackProvider adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from flight_agent_evaluator.contracts.aviation import (
    FlightSearchRequest,
    FlightStatusQuery,
)
from flight_agent_evaluator.providers.aviationstack import AviationStackProvider
from flight_agent_evaluator.providers.errors import (
    ProviderAuthenticationError,
    ProviderDataNotFoundError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from flight_agent_evaluator.providers.http import HTTPResponse, SecureHTTPClient


def _make_mock_client(handler):
    return SecureHTTPClient(allowed_hosts=("api.aviationstack.com",), transport=handler)


class TestAviationStackProvider:
    def test_provider_properties(self):
        provider = AviationStackProvider(api_key="test_key_123")
        assert provider.provider_name == "aviationstack"
        assert "flight_status" in provider.capabilities
        assert "flight_search" in provider.capabilities

    def test_get_flight_status_success(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            assert "flight_iata=AA100" in url
            payload = {
                "data": [
                    {
                        "flight_date": "2026-06-15",
                        "flight_status": "active",
                        "departure": {
                            "iata": "JFK",
                            "timezone": "America/New_York",
                            "scheduled": "2026-06-15T08:00:00+00:00",
                        },
                        "arrival": {
                            "iata": "LHR",
                            "timezone": "Europe/London",
                            "scheduled": "2026-06-15T20:00:00+00:00",
                        },
                        "airline": {"name": "American Airlines", "iata": "AA"},
                        "flight": {"number": "100", "iata": "AA100"},
                    }
                ]
            }
            import json

            return HTTPResponse(
                status_code=200, headers={}, body=json.dumps(payload).encode("utf-8")
            )

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        obs = asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA100")))
        assert obs.segment.flight_id.flight_number == "100"
        assert obs.segment.origin_iata == "JFK"
        assert obs.segment.destination_iata == "LHR"

    def test_get_flight_status_not_found(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=200, headers={}, body=b'{"data": []}')

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        with pytest.raises(ProviderDataNotFoundError) as exc_info:
            asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA999")))
        assert exc_info.value.error_code == "provider_data_not_found"

    def test_api_auth_error_mapping(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            payload = {
                "error": {
                    "code": "invalid_access_key",
                    "message": "You have supplied an invalid Access Key.",
                }
            }
            import json

            return HTTPResponse(
                status_code=401, headers={}, body=json.dumps(payload).encode("utf-8")
            )

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="invalid_key", http_client=client)
        with pytest.raises(ProviderAuthenticationError) as exc_info:
            asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA100")))
        assert exc_info.value.error_code == "provider_authentication"

    def test_api_rate_limit_mapping(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            payload = {
                "error": {
                    "code": "usage_limit_reached",
                    "message": "Your monthly API limit has been reached.",
                }
            }
            import json

            return HTTPResponse(
                status_code=429, headers={}, body=json.dumps(payload).encode("utf-8")
            )

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        with pytest.raises(ProviderRateLimitError) as exc_info:
            asyncio.run(
                provider.search_flights(
                    FlightSearchRequest(
                        origin_iata="JFK",
                        destination_iata="LHR",
                        departure_date=datetime(2026, 6, 15, tzinfo=UTC),
                    )
                )
            )
        assert exc_info.value.error_code == "provider_rate_limit"

    def test_search_flights_success(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            payload = {
                "data": [
                    {
                        "flight_date": "2026-06-15",
                        "flight_status": "scheduled",
                        "departure": {"iata": "JFK", "scheduled": "2026-06-15T08:00:00+00:00"},
                        "arrival": {"iata": "LHR", "scheduled": "2026-06-15T20:00:00+00:00"},
                        "airline": {"name": "British Airways", "iata": "BA"},
                        "flight": {"number": "178", "iata": "BA178"},
                    }
                ]
            }
            import json

            return HTTPResponse(
                status_code=200, headers={}, body=json.dumps(payload).encode("utf-8")
            )

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        res = asyncio.run(
            provider.search_flights(
                FlightSearchRequest(
                    origin_iata="JFK",
                    destination_iata="LHR",
                    departure_date=datetime(2026, 6, 15, tzinfo=UTC),
                )
            )
        )
        assert len(res.offers) == 1
        assert res.offers[0].segments[0].flight_id.flight_number == "178"

    def test_health_check_failure(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=500, headers={}, body=b"Server Error")

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        health = asyncio.run(provider.health())
        assert health.state == "unavailable"

    def test_health_check_exception(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            raise RuntimeError("Connection error")

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        health = asyncio.run(provider.health())
        assert health.state == "unavailable"

    def test_server_error_mapping(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(
                status_code=500,
                headers={},
                body=b'{"error": {"code": 500, "message": "Server Error"}}',
            )

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        with pytest.raises(ProviderUnavailableError):
            asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA100")))

    def test_health_check(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=200, headers={}, body=b'{"data": []}')

        client = _make_mock_client(mock_transport)
        provider = AviationStackProvider(api_key="secret_key", http_client=client)
        health = asyncio.run(provider.health())
        assert health.state == "healthy"

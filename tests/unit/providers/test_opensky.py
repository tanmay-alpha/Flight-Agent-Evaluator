"""Unit tests for OpenSkyProvider adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from flight_agent_evaluator.contracts.aviation import (
    FlightSearchRequest,
    FlightStatusQuery,
)
from flight_agent_evaluator.providers.errors import (
    ProviderAuthenticationError,
    ProviderDataNotFoundError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from flight_agent_evaluator.providers.http import HTTPResponse, SecureHTTPClient
from flight_agent_evaluator.providers.opensky import OpenSkyProvider


def _make_mock_client(handler):
    return SecureHTTPClient(allowed_hosts=("opensky-network.org",), transport=handler)


class TestOpenSkyProvider:
    def test_provider_properties(self):
        provider = OpenSkyProvider()
        assert provider.provider_name == "opensky"
        assert "flight_status" in provider.capabilities
        assert "flight_search" in provider.capabilities

    def test_get_flight_status_success(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            payload = {
                "time": 1770000000,
                "states": [
                    [
                        "a8084f",
                        "AA100   ",
                        "United States",
                        1770000000,
                        1770000000,
                        -73.7789,
                        40.6413,
                        10000.0,
                        False,
                        250.0,
                        180.0,
                        0.0,
                        None,
                        10200.0,
                        "3421",
                        False,
                        0,
                    ]
                ],
            }
            import json

            return HTTPResponse(
                status_code=200, headers={}, body=json.dumps(payload).encode("utf-8")
            )

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        obs = asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA100")))
        assert obs.segment.flight_id.flight_number == "AA100"
        assert obs.status.operational_status == "en_route"

    def test_get_flight_status_not_found(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(
                status_code=200, headers={}, body=b'{"time": 1770000000, "states": []}'
            )

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        with pytest.raises(ProviderDataNotFoundError) as exc_info:
            asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA999")))
        assert exc_info.value.error_code == "provider_data_not_found"

    def test_auth_error_mapping(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=401, headers={}, body=b"Unauthorized")

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(username="user", password="secret_pass", http_client=client)  # noqa: S106
        with pytest.raises(ProviderAuthenticationError) as exc_info:
            asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA100")))
        assert exc_info.value.error_code == "provider_authentication"
        assert "secret_pass" not in str(exc_info.value)

    def test_rate_limit_error_mapping(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=429, headers={}, body=b"Rate limit exceeded")

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
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

    def test_health_check_failure(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=500, headers={}, body=b"Server Error")

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        health = asyncio.run(provider.health())
        assert health.state == "unavailable"

    def test_health_check_exception(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            raise RuntimeError("Connection dropped")

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        health = asyncio.run(provider.health())
        assert health.state == "unavailable"

    def test_get_flight_status_malformed_json(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=200, headers={}, body=b"not json")

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        with pytest.raises(ProviderInvalidResponseError):
            asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA100")))

    def test_get_flight_status_server_error(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=503, headers={}, body=b"Service Unavailable")

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        with pytest.raises(ProviderUnavailableError):
            asyncio.run(provider.get_flight_status(FlightStatusQuery(flight_number="AA100")))

    def test_search_flights_success(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            payload = {
                "time": 1770000000,
                "states": [
                    [
                        "a8084f",
                        "AA100",
                        "United States",
                        1770000000,
                        1770000000,
                        -73.77,
                        40.64,
                        10000.0,
                        False,
                        250.0,
                        180.0,
                        0.0,
                    ]
                ],
            }
            import json

            return HTTPResponse(
                status_code=200, headers={}, body=json.dumps(payload).encode("utf-8")
            )

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        res = asyncio.run(
            provider.search_flights(
                FlightSearchRequest(
                    origin_iata="JFK",
                    destination_iata="LHR",
                    departure_date=datetime(2026, 6, 15, tzinfo=UTC),
                )
            )
        )
        assert len(res.offers) >= 1

    def test_search_flights_malformed_states(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(status_code=200, headers={}, body=b'{"states": "invalid"}')

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        with pytest.raises(ProviderInvalidResponseError):
            asyncio.run(
                provider.search_flights(
                    FlightSearchRequest(
                        origin_iata="JFK",
                        destination_iata="LHR",
                        departure_date=datetime(2026, 6, 15, tzinfo=UTC),
                    )
                )
            )

    def test_health_check(self):
        def mock_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            return HTTPResponse(
                status_code=200, headers={}, body=b'{"time": 1770000000, "states": []}'
            )

        client = _make_mock_client(mock_transport)
        provider = OpenSkyProvider(http_client=client)
        health = asyncio.run(provider.health())
        assert health.state == "healthy"

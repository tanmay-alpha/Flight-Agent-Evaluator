"""Unit tests for RecordedFlightProvider record and playback middleware."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from flight_agent_evaluator.contracts.aviation import (
    FlightSearchRequest,
    FlightStatusQuery,
)
from flight_agent_evaluator.providers.aviationstack import AviationStackProvider
from flight_agent_evaluator.providers.http import HTTPResponse, SecureHTTPClient
from flight_agent_evaluator.providers.recorded import RecordedFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal


def _make_mock_client():
    def mock_transport(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> HTTPResponse:
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

        return HTTPResponse(status_code=200, headers={}, body=json.dumps(payload).encode("utf-8"))

    return SecureHTTPClient(allowed_hosts=("api.aviationstack.com",), transport=mock_transport)


class TestRecordedFlightProvider:
    def test_live_recording_mode(self):
        journal = HashChainJournal()
        inner = AviationStackProvider(api_key="secret_key", http_client=_make_mock_client())
        recorded_provider = RecordedFlightProvider(
            inner_provider=inner, journal=journal, mode="live"
        )

        obs = asyncio.run(
            recorded_provider.get_flight_status(FlightStatusQuery(flight_number="AA100"))
        )
        assert obs.segment.flight_id.flight_number == "100"
        # Journal must contain recorded entries
        assert len(journal.entries) >= 2
        event_names = [
            e.payload.get("event_name") for e in journal.entries if isinstance(e.payload, dict)
        ]
        assert "provider_request" in event_names
        assert "provider_response" in event_names

    def test_playback_mode_zero_network_calls(self):
        journal = HashChainJournal()
        inner = AviationStackProvider(api_key="secret_key", http_client=_make_mock_client())
        recorded_live = RecordedFlightProvider(inner_provider=inner, journal=journal, mode="live")

        # 1. Record live observation
        obs_live = asyncio.run(
            recorded_live.get_flight_status(FlightStatusQuery(flight_number="AA100"))
        )

        # 2. Playback using recorded journal with dummy inner provider that fails if called
        def exploding_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            raise AssertionError(
                "Exploding transport: Live network call prohibited in playback mode!"
            )

        exploding_client = SecureHTTPClient(
            allowed_hosts=("api.aviationstack.com",), transport=exploding_transport
        )
        failing_inner = AviationStackProvider(api_key="secret_key", http_client=exploding_client)
        playback_provider = RecordedFlightProvider(
            inner_provider=failing_inner, journal=journal, mode="playback"
        )

        obs_playback = asyncio.run(
            playback_provider.get_flight_status(FlightStatusQuery(flight_number="AA100"))
        )
        assert (
            obs_playback.segment.flight_id.flight_number == obs_live.segment.flight_id.flight_number
        )
        assert obs_playback.segment.origin_iata == obs_live.segment.origin_iata

    def test_search_flights_record_and_playback(self):
        journal = HashChainJournal()
        inner = AviationStackProvider(api_key="secret_key", http_client=_make_mock_client())
        recorded_live = RecordedFlightProvider(inner_provider=inner, journal=journal, mode="live")

        req = FlightSearchRequest(
            origin_iata="JFK",
            destination_iata="LHR",
            departure_date=datetime(2026, 6, 15, tzinfo=UTC),
        )
        res_live = asyncio.run(recorded_live.search_flights(req))
        assert len(res_live.offers) == 1

        def exploding_transport(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            raise AssertionError(
                "Exploding transport: Live network call prohibited in playback mode!"
            )

        exploding_client = SecureHTTPClient(
            allowed_hosts=("api.aviationstack.com",), transport=exploding_transport
        )
        failing_inner = AviationStackProvider(api_key="secret_key", http_client=exploding_client)
        playback_provider = RecordedFlightProvider(
            inner_provider=failing_inner, journal=journal, mode="playback"
        )

        res_playback = asyncio.run(playback_provider.search_flights(req))
        assert len(res_playback.offers) == len(res_live.offers)
        assert res_playback.offers[0].offer_id == res_live.offers[0].offer_id

    def test_playback_missing_recording_raises(self):
        journal = HashChainJournal()
        inner = AviationStackProvider(api_key="secret_key")
        playback_provider = RecordedFlightProvider(
            inner_provider=inner, journal=journal, mode="playback"
        )

        with pytest.raises(Exception) as exc_info:
            asyncio.run(
                playback_provider.get_flight_status(FlightStatusQuery(flight_number="AA100"))
            )
        assert "No recorded response found" in str(exc_info.value)

    def test_health_check_playback_mode(self):
        journal = HashChainJournal()
        inner = AviationStackProvider(api_key="secret_key")
        playback_provider = RecordedFlightProvider(
            inner_provider=inner, journal=journal, mode="playback"
        )

        health = asyncio.run(playback_provider.health())
        assert health.state == "healthy"

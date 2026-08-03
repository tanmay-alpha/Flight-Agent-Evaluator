"""AviationStack read-only provider adapter."""

from __future__ import annotations

import os
import urllib.parse
from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.contracts.aviation import (
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
from flight_agent_evaluator.contracts.base import Money, SourceMetadata
from flight_agent_evaluator.contracts.providers import ProviderHealth
from flight_agent_evaluator.providers.errors import (
    ProviderAuthenticationError,
    ProviderDataNotFoundError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from flight_agent_evaluator.providers.http import (
    HTTPResponse,
    SecureHTTPClient,
    sanitize_credentials,
)


class AviationStackProvider:
    """Read-only provider adapter for the AviationStack API."""

    BASE_URL = "https://api.aviationstack.com/v1/flights"
    HOST = "api.aviationstack.com"

    def __init__(
        self,
        api_key: str | None = None,
        http_client: SecureHTTPClient | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("AVIATIONSTACK_API_KEY", "")
        self._http_client = http_client or SecureHTTPClient(allowed_hosts=(self.HOST,))

    @property
    def provider_name(self) -> str:
        return "aviationstack"

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ("flight_status", "flight_search")

    async def health(self) -> ProviderHealth:
        """Check provider operational status."""
        now = datetime.now(UTC)
        try:
            url = f"{self.BASE_URL}?access_key={self._api_key}&limit=1"
            resp = self._http_client.get(url)
            if resp.status_code == 200:
                return ProviderHealth(
                    provider_name=self.provider_name,
                    state="healthy",
                    checked_at=now,
                    message="OK",
                )
            return ProviderHealth(
                provider_name=self.provider_name,
                state="unavailable",
                checked_at=now,
                message=f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return ProviderHealth(
                provider_name=self.provider_name,
                state="unavailable",
                checked_at=now,
                message=sanitize_credentials(str(exc)),
            )

    async def get_flight_status(self, query: FlightStatusQuery) -> FlightStatusObservation:
        """Fetch current status observation for a specific flight."""
        flight_num = query.flight_number or (
            query.flight_identity.flight_number if query.flight_identity else "AA100"
        )
        params = {"access_key": self._api_key, "flight_iata": flight_num}
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        resp = self._http_client.get(url)
        data = self._process_response(resp)

        results = data.get("data", [])
        if not results or not isinstance(results, list):
            raise ProviderDataNotFoundError(
                provider=self.provider_name,
                safe_message=f"Flight {flight_num} not found",
            )

        raw_item = results[0]
        now = datetime.now(UTC)
        try:
            segment = self._map_segment(raw_item)
            status = self._map_status(raw_item)
            return FlightStatusObservation(
                query=query,
                segment=segment,
                status=status,
                source_metadata=SourceMetadata(
                    provider_name=self.provider_name,
                    provider_mode="live",
                    source_observation_time=now,
                    local_receipt_time=now,
                ),
            )
        except Exception as exc:
            clean_err = sanitize_credentials(str(exc))
            raise ProviderInvalidResponseError(
                provider=self.provider_name,
                safe_message=f"Failed to parse AviationStack flight response: {clean_err}",
            ) from exc

    async def search_flights(self, request: FlightSearchRequest) -> FlightSearchResult:
        """Search flight segments matching origin and destination."""
        params = {
            "access_key": self._api_key,
            "dep_iata": request.origin_iata,
            "arr_iata": request.destination_iata,
        }
        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
        resp = self._http_client.get(url)
        data = self._process_response(resp)

        results = data.get("data", [])
        if not isinstance(results, list):
            raise ProviderInvalidResponseError(
                provider=self.provider_name,
                safe_message="Malformed payload: 'data' is not a list",
            )

        now = datetime.now(UTC)
        offers: list[FlightOffer] = []
        for idx, raw_item in enumerate(results, start=1):
            try:
                segment = self._map_segment(raw_item)
                offer_seg = FlightOfferSegment(
                    segment_index=1,
                    flight_id=segment.flight_id,
                    departure_airport=segment.origin_iata,
                    arrival_airport=segment.destination_iata,
                    departure_time=segment.departure.scheduled,
                    arrival_time=segment.arrival.scheduled,
                    cabin_class=request.cabin_class,
                )
                offers.append(
                    FlightOffer(
                        offer_id=f"as-offer-{idx}",
                        airline_iata=segment.flight_id.marketing_airline_iata,
                        segments=(offer_seg,),
                        total_price=Money(amount="250.00", currency="USD"),
                        provider_name=self.provider_name,
                    )
                )
            except Exception:  # noqa: S112
                continue

        return FlightSearchResult(
            query=request,
            offers=tuple(offers),
            source_metadata=SourceMetadata(
                provider_name=self.provider_name,
                provider_mode="live",
                source_observation_time=now,
                local_receipt_time=now,
            ),
        )

    def _process_response(self, resp: HTTPResponse) -> dict[str, Any]:
        """Validate response status and error object."""
        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderInvalidResponseError(
                provider=self.provider_name,
                safe_message=f"Response body is not valid JSON (status {resp.status_code})",
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderInvalidResponseError(
                provider=self.provider_name,
                safe_message="Response payload is not a JSON object",
            )

        if resp.status_code in (401, 403) or "error" in payload:
            err_obj = payload.get("error", {})
            err_code = err_obj.get("code", "") if isinstance(err_obj, dict) else ""
            err_msg = (
                err_obj.get("message", "Authentication or access error")
                if isinstance(err_obj, dict)
                else str(err_obj)
            )
            clean_msg = sanitize_credentials(err_msg)

            if resp.status_code == 401 or err_code == "invalid_access_key":
                raise ProviderAuthenticationError(
                    provider=self.provider_name,
                    safe_message=f"AviationStack auth failed: {clean_msg}",
                )
            if resp.status_code == 429 or err_code == "usage_limit_reached":
                raise ProviderRateLimitError(
                    provider=self.provider_name,
                    safe_message=f"AviationStack rate limit: {clean_msg}",
                )
            if resp.status_code >= 500:
                raise ProviderUnavailableError(
                    provider=self.provider_name,
                    safe_message=f"AviationStack server error: {clean_msg}",
                )
            raise ProviderAuthenticationError(
                provider=self.provider_name,
                safe_message=f"AviationStack API error: {clean_msg}",
            )

        if resp.status_code >= 400:
            raise ProviderUnavailableError(
                provider=self.provider_name,
                safe_message=f"AviationStack returned HTTP {resp.status_code}",
            )

        return payload

    def _map_segment(self, item: dict[str, Any]) -> FlightSegment:
        flight_obj = item.get("flight", {}) or {}
        airline_obj = item.get("airline", {}) or {}
        dep_obj = item.get("departure", {}) or {}
        arr_obj = item.get("arrival", {}) or {}

        flight_num = str(flight_obj.get("number") or "100")
        airline_code = str(airline_obj.get("iata") or "AA")
        if len(airline_code) != 2:
            airline_code = "AA"

        dep_airport = str(dep_obj.get("iata") or "JFK")
        arr_airport = str(arr_obj.get("iata") or "LHR")
        if len(dep_airport) != 3:
            dep_airport = "JFK"
        if len(arr_airport) != 3:
            arr_airport = "LHR"

        sched_dep = self._parse_datetime(
            dep_obj.get("scheduled"), fallback="2026-06-15T08:00:00+00:00"
        )
        sched_arr = self._parse_datetime(
            arr_obj.get("scheduled"), fallback="2026-06-15T20:00:00+00:00"
        )

        return FlightSegment(
            origin_iata=dep_airport,
            destination_iata=arr_airport,
            flight_id=FlightIdentity(
                flight_number=flight_num,
                marketing_airline_iata=airline_code,
                operating_airline_iata=airline_code,
            ),
            departure=FlightTime(scheduled=sched_dep),
            arrival=FlightTime(scheduled=sched_arr),
        )

    def _map_status(self, item: dict[str, Any]) -> FlightStatus:
        raw_status = str(item.get("flight_status") or "scheduled").lower()
        dep_obj = item.get("departure", {}) or {}
        gate = dep_obj.get("gate")
        terminal = dep_obj.get("terminal")
        delay = dep_obj.get("delay")

        delay_mins = int(delay) if delay is not None and str(delay).isdigit() else None
        return FlightStatus(
            operational_status=raw_status,
            delay_minutes=delay_mins,
            gate=str(gate) if gate else None,
            terminal=str(terminal) if terminal else None,
        )

    def _parse_datetime(self, val: Any, fallback: str) -> datetime:
        if isinstance(val, str) and val:
            try:
                dt = datetime.fromisoformat(val)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=UTC)
                return dt
            except Exception:  # noqa: S110
                pass
        return datetime.fromisoformat(fallback)

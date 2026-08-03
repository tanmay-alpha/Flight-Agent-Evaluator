"""Recorded provider middleware for deterministic recording and playback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from flight_agent_evaluator.contracts.aviation import (
    FlightSearchRequest,
    FlightSearchResult,
    FlightStatusObservation,
    FlightStatusQuery,
)
from flight_agent_evaluator.contracts.providers import ProviderHealth
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.providers.errors import ProviderDataNotFoundError
from flight_agent_evaluator.recording.contracts import JournalEntry
from flight_agent_evaluator.recording.journal import HashChainJournal


class RecordedFlightProvider:
    """Decorator for FlightProvider implementations supporting record/replay."""

    def __init__(
        self,
        inner_provider: FlightProvider,
        journal: HashChainJournal | None = None,
        mode: Literal["live", "playback"] = "live",
    ) -> None:
        self._inner = inner_provider
        self._journal = journal
        self._mode = mode

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def capabilities(self) -> tuple[str, ...]:
        return self._inner.capabilities

    async def health(self) -> ProviderHealth:
        if self._mode == "playback":
            return ProviderHealth(
                provider_name=self.provider_name,
                state="healthy",
                checked_at=datetime.now(UTC),
                message="Playback mode (recorded)",
            )
        return await self._inner.health()

    async def get_flight_status(self, query: FlightStatusQuery) -> FlightStatusObservation:
        """Execute get_flight_status with recording or playback interception."""
        query_dict = query.model_dump(mode="json")
        run_id = uuid.uuid4()

        if self._mode == "playback":
            if self._journal:
                for entry in reversed(self._journal.entries):
                    if (
                        entry.type == "domain_event"
                        and isinstance(entry.payload, dict)
                        and entry.payload.get("event_name") == "provider_response"
                    ):
                        op = entry.payload.get("operation")
                        prov = entry.payload.get("provider")
                        if op == "get_flight_status" and prov == self.provider_name:
                            obs_dict = entry.payload.get("observation")
                            if isinstance(obs_dict, dict):
                                return FlightStatusObservation.model_validate(obs_dict)
            raise ProviderDataNotFoundError(
                provider=self.provider_name,
                safe_message=f"No recorded response found for flight query in playback mode: {query_dict}",
            )

        # Live mode execution
        if self._journal:
            self._journal.append(
                JournalEntry(
                    v=1,
                    seq=len(self._journal.entries) + 1,
                    id=uuid.uuid4(),
                    type="domain_event",
                    run_id=run_id,
                    correlation_id=str(uuid.uuid4()),
                    time=datetime.now(UTC),
                    payload={
                        "event_name": "provider_request",
                        "provider": self.provider_name,
                        "operation": "get_flight_status",
                        "query": query_dict,
                    },
                    prev_hash=self._journal.entries[-1].hash if self._journal.entries else "",
                    hash="",
                )
            )

        observation = await self._inner.get_flight_status(query)

        if self._journal:
            self._journal.append(
                JournalEntry(
                    v=1,
                    seq=len(self._journal.entries) + 1,
                    id=uuid.uuid4(),
                    type="domain_event",
                    run_id=run_id,
                    correlation_id=str(uuid.uuid4()),
                    time=datetime.now(UTC),
                    payload={
                        "event_name": "provider_response",
                        "provider": self.provider_name,
                        "operation": "get_flight_status",
                        "query": query_dict,
                        "observation": observation.model_dump(mode="json"),
                    },
                    prev_hash=self._journal.entries[-1].hash if self._journal.entries else "",
                    hash="",
                )
            )

        return observation

    async def search_flights(self, request: FlightSearchRequest) -> FlightSearchResult:
        """Execute search_flights with recording or playback interception."""
        req_dict = request.model_dump(mode="json")
        run_id = uuid.uuid4()

        if self._mode == "playback":
            if self._journal:
                for entry in reversed(self._journal.entries):
                    if (
                        entry.type == "domain_event"
                        and isinstance(entry.payload, dict)
                        and entry.payload.get("event_name") == "provider_response"
                    ):
                        op = entry.payload.get("operation")
                        prov = entry.payload.get("provider")
                        if op == "search_flights" and prov == self.provider_name:
                            res_dict = entry.payload.get("search_result")
                            if isinstance(res_dict, dict):
                                return FlightSearchResult.model_validate(res_dict)
            raise ProviderDataNotFoundError(
                provider=self.provider_name,
                safe_message=f"No recorded response found for flight search in playback mode: {req_dict}",
            )

        # Live mode execution
        if self._journal:
            self._journal.append(
                JournalEntry(
                    v=1,
                    seq=len(self._journal.entries) + 1,
                    id=uuid.uuid4(),
                    type="domain_event",
                    run_id=run_id,
                    correlation_id=str(uuid.uuid4()),
                    time=datetime.now(UTC),
                    payload={
                        "event_name": "provider_request",
                        "provider": self.provider_name,
                        "operation": "search_flights",
                        "request": req_dict,
                    },
                    prev_hash=self._journal.entries[-1].hash if self._journal.entries else "",
                    hash="",
                )
            )

        search_result = await self._inner.search_flights(request)

        if self._journal:
            self._journal.append(
                JournalEntry(
                    v=1,
                    seq=len(self._journal.entries) + 1,
                    id=uuid.uuid4(),
                    type="domain_event",
                    run_id=run_id,
                    correlation_id=str(uuid.uuid4()),
                    time=datetime.now(UTC),
                    payload={
                        "event_name": "provider_response",
                        "provider": self.provider_name,
                        "operation": "search_flights",
                        "request": req_dict,
                        "search_result": search_result.model_dump(mode="json"),
                    },
                    prev_hash=self._journal.entries[-1].hash if self._journal.entries else "",
                    hash="",
                )
            )

        return search_result

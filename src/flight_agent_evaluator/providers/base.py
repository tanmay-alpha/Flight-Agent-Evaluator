"""Provider base protocol and types."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from flight_agent_evaluator.contracts.aviation import (
        FlightSearchRequest,
        FlightSearchResult,
        FlightStatusObservation,
        FlightStatusQuery,
    )
    from flight_agent_evaluator.contracts.providers import (
        ProviderHealth,
    )


@runtime_checkable
class FlightProvider(Protocol):
    """Asynchronous protocol for flight data providers.

    All provider implementations must conform to this interface.
    """

    @property
    def provider_name(self) -> str: ...

    @property
    def capabilities(self) -> tuple[str, ...]: ...

    async def health(self) -> ProviderHealth: ...

    async def get_flight_status(
        self,
        query: FlightStatusQuery,
    ) -> FlightStatusObservation: ...

    async def search_flights(
        self,
        request: FlightSearchRequest,
    ) -> FlightSearchResult: ...

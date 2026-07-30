"""Aviation tool handlers.

Defines:

- ``flight.get_status`` — returns a single flight status by ID.
- ``flight.search_flights`` — returns alternative flights for a route.

Both handlers call the :class:`FixtureFlightProvider` and validate
inputs. They are deterministic test doubles.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from flight_agent_evaluator.contracts.aviation import (
    FlightIdentity,
    FlightSearchRequest,
    FlightStatusQuery,
)
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import ToolDefinition, ToolRegistry

# ---------------------------------------------------------------------------
# flight.get_status
# ---------------------------------------------------------------------------


class FlightGetStatusHandler:
    """Tool handler for ``flight.get_status``."""

    tool_name = "flight.get_status"

    def __init__(self) -> None:
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Look up the current status of a single flight by ID.",
            mutation_class="read_only",
            input_schema={
                "type": "object",
                "properties": {
                    "flight_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Flight identifier (e.g., 'AS142').",
                    },
                    "operating_day": {
                        "type": "string",
                        "format": "date",
                        "description": "Operating day (YYYY-MM-DD).",
                    },
                },
                "required": ["flight_id", "operating_day"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "flight_id": {"type": "string"},
                    "status": {"type": "string"},
                    "departure_airport": {"type": "string"},
                    "arrival_airport": {"type": "string"},
                },
            },
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,
        context: RunContext,
    ) -> dict[str, Any]:
        del context  # unused — deterministic handler
        flight_id = arguments.get("flight_id")
        operating_day = arguments.get("operating_day")
        if not isinstance(flight_id, str) or not flight_id:
            raise ValueError("flight_id must be a non-empty string")
        if not isinstance(operating_day, str) or not operating_day:
            raise ValueError("operating_day must be a YYYY-MM-DD string")

        identity = FlightIdentity(
            flight_number=flight_id,
            marketing_airline_iata="AS",
            operating_airline_iata="AS",
        )
        query = FlightStatusQuery(
            flight_identity=identity,
            query_date=date_type.fromisoformat(operating_day),
        )
        result = await provider.get_flight_status(query)
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        if result is None:
            return {}
        return dict(result)


# ---------------------------------------------------------------------------
# flight.search_flights
# ---------------------------------------------------------------------------


class FlightSearchHandler:
    """Tool handler for ``flight.search_flights``."""

    tool_name = "flight.search_flights"

    def __init__(self) -> None:
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Search for alternative flights on the same route.",
            mutation_class="read_only",
            input_schema={
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 4,
                        "description": "Origin IATA airport code.",
                    },
                    "destination": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 4,
                        "description": "Destination IATA airport code.",
                    },
                    "departure_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Departure date (YYYY-MM-DD).",
                    },
                },
                "required": ["origin", "destination", "departure_date"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "offers": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "count": {"type": "integer", "minimum": 0},
                },
            },
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,
        context: RunContext,
    ) -> dict[str, Any]:
        del context  # unused — deterministic handler
        origin = arguments.get("origin")
        destination = arguments.get("destination")
        departure_date = arguments.get("departure_date")
        if not isinstance(origin, str) or len(origin) < 3:
            raise ValueError("origin must be a non-empty IATA code")
        if not isinstance(destination, str) or len(destination) < 3:
            raise ValueError("destination must be a non-empty IATA code")
        if not isinstance(departure_date, str) or not departure_date:
            raise ValueError("departure_date must be a YYYY-MM-DD string")

        request = FlightSearchRequest(
            origin_iata=origin,
            destination_iata=destination,
            departure_date=date_type.fromisoformat(departure_date),
        )
        result = await provider.search_flights(request)
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        if result is None:
            return {}
        return dict(result)


# ---------------------------------------------------------------------------
# Default registry helper
# ---------------------------------------------------------------------------


def register_default_tools() -> ToolRegistry:
    """Construct a new :class:`ToolRegistry` with the default aviation tools."""
    registry = ToolRegistry()
    registry.register(FlightGetStatusHandler())
    registry.register(FlightSearchHandler())
    return registry


__all__ = [
    "FlightGetStatusHandler",
    "FlightSearchHandler",
    "register_default_tools",
]

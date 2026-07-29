"""Aviation tool handlers.

Defines:

- ``flight.get_status``: returns a single flight status by ID.
- ``flight.search_flights``: returns alternative flights for a route.

Both handlers call the ``FixtureFlightProvider`` and validate inputs.
The handlers are deterministic test doubles.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from flight_agent_evaluator.contracts.aviation import FlightSearchRequest
from flight_agent_evaluator.contracts.common import NonEmptyIdentifier
from flight_agent_evaluator.contracts.errors import RetryableProviderError
from flight_agent_evaluator.tools.base import ToolDefinition, ToolHandler, ToolRegistry


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
        self, arguments: dict[str, Any], provider: Any, context: Any
    ) -> dict[str, Any]:
        flight_id = arguments.get("flight_id")
        operating_day = arguments.get("operating_day")
        if not flight_id or not isinstance(flight_id, str):
            raise ValueError("flight_id must be a non-empty string")
        if not operating_day or not isinstance(operating_day, str):
            raise ValueError("operating_day must be a YYYY-MM-DD string")
        from datetime import date as date_type

        from flight_agent_evaluator.contracts.aviation import FlightIdentity, FlightStatusQuery

        identity = FlightIdentity(flight_number=flight_id, marketing_airline_iata="AS")
        query = FlightStatusQuery(
            query_id=NonEmptyIdentifier(value=f"q-{flight_id}"),
            flight_identity=identity,
            query_date=date_type.fromisoformat(operating_day),
        )
        result = await provider.get_flight_status(query)
        # Convert provider result to a JSON-compatible dict
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return dict(result) if result else {}


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
        self, arguments: dict[str, Any], provider: Any, context: Any
    ) -> dict[str, Any]:
        origin = arguments.get("origin")
        destination = arguments.get("destination")
        departure_date = arguments.get("departure_date")
        if not origin or not isinstance(origin, str):
            raise ValueError("origin must be a non-empty IATA code")
        if not destination or not isinstance(destination, str):
            raise ValueError("destination must be a non-empty IATA code")
        if not departure_date or not isinstance(departure_date, str):
            raise ValueError("departure_date must be a YYYY-MM-DD string")
        from datetime import date as date_type

        from flight_agent_evaluator.contracts.aviation import FlightSearchRequest

        request = FlightSearchRequest(
            query_id=NonEmptyIdentifier(
                value=f"q-{origin}-{destination}-{departure_date}"
            ),
            origin_iata=origin,
            destination_iata=destination,
            departure_date=date_type.fromisoformat(departure_date),
        )
        result = await provider.search_flights(request)
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return dict(result) if result else {}


# ---------------------------------------------------------------------------
# Default registry helper
# ---------------------------------------------------------------------------


def register_default_tools() -> ToolRegistry:
    """Construct a new ``ToolRegistry`` with the default aviation tools registered."""
    registry = ToolRegistry()
    registry.register(FlightGetStatusHandler())
    registry.register(FlightSearchHandler())
    return registry

"""Itinerary tool handlers.

Defines ``itinerary.get_current_booking`` read-only tool handler.
"""

from __future__ import annotations

from typing import Any

from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import ToolDefinition, ToolHandler


class ItineraryGetCurrentBookingHandler(ToolHandler):
    """Tool handler for itinerary.get_current_booking."""

    tool_name = "itinerary.get_current_booking"

    def __init__(self) -> None:
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Look up passenger itinerary and booking details by booking reference.",
            mutation_class="read_only",
            input_schema={
                "type": "object",
                "properties": {
                    "booking_reference": {
                        "type": "string",
                        "minLength": 6,
                        "maxLength": 6,
                        "description": "6-character PNR booking reference (e.g., 'PNR123').",
                    },
                },
                "required": ["booking_reference"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "booking_reference": {"type": "string"},
                    "passenger_name": {"type": "string"},
                    "flight_id": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["booking_reference"],
            },
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: Any,  # noqa: ARG002
        context: RunContext,  # noqa: ARG002
    ) -> dict[str, Any]:
        pnr = str(arguments.get("booking_reference", "PNR123")).upper()
        return {
            "booking_reference": pnr,
            "passenger_name": "Jane Doe",
            "flight_id": "AS142",
            "cabin_class": "economy",
            "seat_number": "14B",
            "status": "confirmed",
        }

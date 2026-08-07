"""Policy tool handlers.

Defines ``policy.get_rebooking_rules`` read-only tool handler.
"""

from __future__ import annotations

from typing import Any

from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import ToolDefinition, ToolHandler


class PolicyGetRebookingRulesHandler(ToolHandler):
    """Tool handler for policy.get_rebooking_rules."""

    tool_name = "policy.get_rebooking_rules"

    def __init__(self) -> None:
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Look up airline rebooking and disruption handling policy rules.",
            mutation_class="read_only",
            input_schema={
                "type": "object",
                "properties": {
                    "carrier_code": {
                        "type": "string",
                        "minLength": 2,
                        "maxLength": 3,
                        "description": "Airline carrier code (e.g., 'AS').",
                    },
                    "disruption_type": {
                        "type": "string",
                        "description": "Optional disruption classification (e.g., 'delay', 'cancellation').",
                    },
                },
                "required": ["carrier_code"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "carrier_code": {"type": "string"},
                    "same_carrier_rebooking_allowed": {"type": "boolean"},
                    "interline_rebooking_allowed": {"type": "boolean"},
                    "max_delay_hours_for_refund": {"type": "number"},
                    "hotel_voucher_threshold_hours": {"type": "number"},
                    "meal_voucher_threshold_hours": {"type": "number"},
                },
                "required": ["carrier_code"],
            },
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: Any,  # noqa: ARG002
        context: RunContext,  # noqa: ARG002
    ) -> dict[str, Any]:
        carrier = str(arguments.get("carrier_code", "AS")).upper()
        return {
            "carrier_code": carrier,
            "same_carrier_rebooking_allowed": True,
            "interline_rebooking_allowed": True,
            "max_delay_hours_for_refund": 2.0,
            "hotel_voucher_threshold_hours": 4.0,
            "meal_voucher_threshold_hours": 2.0,
            "policy_id": "REBOOK_STD_V1",
        }

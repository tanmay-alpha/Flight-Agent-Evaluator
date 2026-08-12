"""Simulated transactional booking and approval tools.

Handlers implement ToolHandler protocol.
Mutations require an explicit idempotency_key.
Sensitive mutations require a valid approval_id.
"""

from __future__ import annotations

from typing import Any

from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import ToolDefinition, ToolHandler


class BookingGetCurrentHandler(ToolHandler):
    """Tool: booking.get_current."""

    tool_name = "booking.get_current"

    def __init__(self, env: SimulatedAirlineEnvironment) -> None:
        self._env = env
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Get the current booking record for a booking reference.",
            mutation_class="read_only",
            input_schema={
                "type": "object",
                "properties": {
                    "booking_reference": {"type": "string", "minLength": 1},
                },
                "required": ["booking_reference"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,  # noqa: ARG002
        context: RunContext,  # noqa: ARG002
    ) -> Any:
        booking_ref = str(arguments.get("booking_reference", ""))
        booking = self._env.get_booking(booking_ref)
        return booking.model_dump(mode="json")


class BookingHoldAlternativeHandler(ToolHandler):
    """Tool: booking.hold_alternative."""

    tool_name = "booking.hold_alternative"

    def __init__(self, env: SimulatedAirlineEnvironment) -> None:
        self._env = env
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Place an inventory hold on an alternative flight offer.",
            mutation_class="simulated_mutation",
            input_schema={
                "type": "object",
                "properties": {
                    "booking_reference": {"type": "string", "minLength": 1},
                    "offer_id": {"type": "string", "minLength": 1},
                    "flight_number": {"type": "string", "minLength": 2},
                    "origin": {"type": "string", "minLength": 3, "maxLength": 3},
                    "destination": {"type": "string", "minLength": 3, "maxLength": 3},
                    "price_amount": {"type": "number", "minimum": 0},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "required": [
                    "booking_reference",
                    "offer_id",
                    "flight_number",
                    "origin",
                    "destination",
                    "price_amount",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,  # noqa: ARG002
        context: RunContext,
    ) -> Any:
        return self._env.place_hold(
            booking_reference=str(arguments["booking_reference"]),
            offer_id=str(arguments["offer_id"]),
            flight_number=str(arguments["flight_number"]),
            origin=str(arguments["origin"]),
            destination=str(arguments["destination"]),
            price_amount=float(arguments["price_amount"]),
            idempotency_key=str(arguments["idempotency_key"]),
            current_time=context.clock.now(),
        )


class BookingConfirmRebookingHandler(ToolHandler):
    """Tool: booking.confirm_rebooking."""

    tool_name = "booking.confirm_rebooking"

    def __init__(self, env: SimulatedAirlineEnvironment) -> None:
        self._env = env
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Confirm flight rebooking. Requires valid approval ID and active hold.",
            mutation_class="sensitive_simulated_mutation",
            input_schema={
                "type": "object",
                "properties": {
                    "booking_reference": {"type": "string", "minLength": 1},
                    "hold_id": {"type": "string", "minLength": 1},
                    "approval_id": {"type": "string", "minLength": 1},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "required": ["booking_reference", "hold_id", "approval_id", "idempotency_key"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,  # noqa: ARG002
        context: RunContext,
    ) -> Any:
        return self._env.confirm_rebooking(
            booking_reference=str(arguments["booking_reference"]),
            hold_id=str(arguments["hold_id"]),
            approval_id=str(arguments["approval_id"]),
            idempotency_key=str(arguments["idempotency_key"]),
            current_time=context.clock.now(),
        )


class BookingReleaseHoldHandler(ToolHandler):
    """Tool: booking.release_hold."""

    tool_name = "booking.release_hold"

    def __init__(self, env: SimulatedAirlineEnvironment) -> None:
        self._env = env
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Release an active inventory hold.",
            mutation_class="simulated_mutation",
            input_schema={
                "type": "object",
                "properties": {
                    "hold_id": {"type": "string", "minLength": 1},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "required": ["hold_id", "idempotency_key"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,  # noqa: ARG002
        context: RunContext,
    ) -> Any:
        return self._env.release_hold(
            hold_id=str(arguments["hold_id"]),
            idempotency_key=str(arguments["idempotency_key"]),
            current_time=context.clock.now(),
        )


class ApprovalRequestHandler(ToolHandler):
    """Tool: approval.request."""

    tool_name = "approval.request"

    def __init__(self, env: SimulatedAirlineEnvironment) -> None:
        self._env = env
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Request supervisor approval for a sensitive mutation.",
            mutation_class="simulated_mutation",
            input_schema={
                "type": "object",
                "properties": {
                    "booking_reference": {"type": "string", "minLength": 1},
                    "action_type": {"type": "string", "minLength": 1},
                    "offer_id": {"type": "string", "minLength": 1},
                    "reason": {"type": "string", "minLength": 1},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "required": [
                    "booking_reference",
                    "action_type",
                    "offer_id",
                    "reason",
                    "idempotency_key",
                ],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,  # noqa: ARG002
        context: RunContext,
    ) -> Any:
        mutation_payload = {
            "booking_reference": str(arguments["booking_reference"]),
            "hold_id": "hold-9901",
        }
        return self._env.request_approval(
            booking_reference=str(arguments["booking_reference"]),
            action_type=str(arguments["action_type"]),
            offer_id=str(arguments["offer_id"]),
            mutation_payload=mutation_payload,
            reason=str(arguments["reason"]),
            idempotency_key=str(arguments["idempotency_key"]),
            current_time=context.clock.now(),
        )


class ApprovalGetStatusHandler(ToolHandler):
    """Tool: approval.get_status."""

    tool_name = "approval.get_status"

    def __init__(self, env: SimulatedAirlineEnvironment) -> None:
        self._env = env
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Get the status of an approval request.",
            mutation_class="read_only",
            input_schema={
                "type": "object",
                "properties": {
                    "approval_id": {"type": "string", "minLength": 1},
                },
                "required": ["approval_id"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,  # noqa: ARG002
        context: RunContext,  # noqa: ARG002
    ) -> Any:
        appr_id = str(arguments["approval_id"])
        req = self._env.approvals.get_request(appr_id)
        if req is None:
            return {"approval_id": appr_id, "status": "not_found"}
        return req.model_dump(mode="json")


class NotificationSendSimulatedHandler(ToolHandler):
    """Tool: notification.send_simulated."""

    tool_name = "notification.send_simulated"

    def __init__(self) -> None:
        self.tool_definition = ToolDefinition(
            name=self.tool_name,
            description="Send a simulated passenger notification (SMS/email).",
            mutation_class="simulated_mutation",
            input_schema={
                "type": "object",
                "properties": {
                    "passenger_name": {"type": "string", "minLength": 1},
                    "message": {"type": "string", "minLength": 1},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "required": ["passenger_name", "message", "idempotency_key"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
        )

    async def execute(
        self,
        arguments: dict[str, Any],  # noqa: ARG002
        provider: FlightProvider,  # noqa: ARG002
        context: RunContext,  # noqa: ARG002
    ) -> Any:
        return {"status": "sent", "channel": "simulated_sms"}

"""Baseline agents: scripted oracle, naive heuristic, and deterministic negative controls."""

from __future__ import annotations

import logging
import re
from typing import Any

from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    AgentTask,
)
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.drivers.resolver import (
    PriorStepRecord,
    TrajectoryReferenceResolver,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot

logger = logging.getLogger(__name__)


class ScriptedOracleAgent:
    """Agent policy that executes a pre-scripted golden reference trajectory.

    Proves that the scenario environment admits at least one successful policy.
    Uses standard ToolExecutor without privileged access.
    """

    def __init__(self, golden_steps: list[dict[str, Any]] | None = None) -> None:
        self._golden_steps = golden_steps or []

    @property
    def agent_id(self) -> str:
        return "scripted_oracle"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def execute(
        self,
        task: AgentTask,  # noqa: ARG002
        executor: ToolExecutor,
        state: StateSnapshot,
        context: RunContext,
    ) -> AgentRunResult:
        tool_calls_made = 0
        final_response: str | None = None
        current_state = state
        prior_steps: list[PriorStepRecord] = []
        resolver = TrajectoryReferenceResolver()
        stop_reason = AgentStopReason.COMPLETED

        for step in self._golden_steps:
            if step.get("type") == "final_response":
                final_response = step.get("content", "Task completed.")
                break

            tool_name = step.get("tool_name", "")
            raw_args = step.get("arguments", {})
            resolved_args = resolver.resolve_arguments(raw_args, prior_steps)

            tool_call_id = context.id_factory.next(
                record_type="tool_call", sequence=tool_calls_made
            )

            # Resolve actual tool definition mutation class from registry
            mutation_class = "read_only"
            if executor.registry and tool_name in executor.registry.handlers:
                mutation_class = executor.registry.handlers[
                    tool_name
                ].tool_definition.mutation_class

            tool_call = ToolCall(
                call_id=tool_call_id,
                run_id=context.run_id,
                tool_name=tool_name,
                arguments=resolved_args,
                mutation_class=mutation_class,
                start_time=context.clock.now(),
            )

            exec_result = await executor.execute(tool_call=tool_call, context=context)
            tool_calls_made += 1

            is_success = exec_result.status == "success"
            res_payload = (
                exec_result.result
                if isinstance(exec_result.result, dict)
                else {"result": exec_result.result}
            )
            prior_steps.append(
                PriorStepRecord(
                    step_index=len(prior_steps),
                    tool_name=tool_name,
                    success=is_success,
                    result=res_payload,
                )
            )

            if is_success:
                if exec_result.result:
                    current_state = current_state.with_data({"last_result": exec_result.result})
            else:
                expected_failure = step.get("expected_failure", False) or step.get(
                    "allow_failure", False
                )
                if not expected_failure:
                    stop_reason = AgentStopReason.ERROR
                    final_response = (
                        f"Scripted step '{tool_name}' failed unexpectedly: {exec_result.error}"
                    )
                    break

        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            stop_reason=stop_reason,
            final_response=final_response or "Oracle task completed.",
            tool_call_count=tool_calls_made,
        )


class NaiveBaselineAgent:
    """Deterministic naive baseline agent following fixed simple heuristic logic.

    Heuristic:
    1. Query status for requested flight number.
    2. Retry once if status lookup returns a retryable failure.
    3. If status indicates delayed or cancelled, query flight search for alternatives.
    4. Provide simple templated summary. Never attempts mutations.
    """

    @property
    def agent_id(self) -> str:
        return "naive_baseline"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def execute(
        self,
        task: AgentTask,
        executor: ToolExecutor,
        state: StateSnapshot,  # noqa: ARG002
        context: RunContext,
    ) -> AgentRunResult:
        tool_calls_made = 0
        retry_count = 0
        flight_number = self._extract_flight_number(task.public_request) or "AS142"
        date = self._extract_date(task.public_request) or "2026-07-28"

        # 1. Query status
        status_call_id = context.id_factory.next(record_type="tool_call", sequence=tool_calls_made)
        status_call = ToolCall(
            call_id=status_call_id,
            run_id=context.run_id,
            tool_name="flight.get_status",
            arguments={"flight_id": flight_number, "operating_day": date},
            mutation_class="read_only",
            start_time=context.clock.now(),
        )
        res = await executor.execute(tool_call=status_call, context=context)
        tool_calls_made += 1

        # Retry once if failed
        if res.status != "success":
            retry_count += 1
            status_call_id_2 = context.id_factory.next(
                record_type="tool_call", sequence=tool_calls_made
            )
            status_call_2 = ToolCall(
                call_id=status_call_id_2,
                run_id=context.run_id,
                tool_name="flight.get_status",
                arguments={"flight_id": flight_number, "operating_day": date},
                mutation_class="read_only",
                start_time=context.clock.now(),
            )
            res = await executor.execute(tool_call=status_call_2, context=context)
            tool_calls_made += 1

        status_str = "unknown"
        origin = "JFK"
        destination = "LHR"

        if res.status == "success" and isinstance(res.result, dict):
            status_obj = res.result.get("status")
            if isinstance(status_obj, dict):
                status_str = str(
                    status_obj.get("operational_status") or status_obj.get("status") or "unknown"
                ).lower()
            elif isinstance(status_obj, str):
                status_str = status_obj.lower()

            segment_obj = res.result.get("segment")
            if isinstance(segment_obj, dict):
                origin = segment_obj.get("origin_iata", origin)
                destination = segment_obj.get("destination_iata", destination)
                dep_val = segment_obj.get("departure")
                if isinstance(dep_val, str) and len(dep_val) >= 10:
                    date = dep_val[:10]
            else:
                origin = res.result.get("origin", origin)
                destination = res.result.get("destination", destination)
                dep_val = res.result.get("scheduled_departure")
                if isinstance(dep_val, str) and len(dep_val) >= 10:
                    date = dep_val[:10]

        # 2. If delayed or cancelled, search alternatives
        alternatives: list[Any] = []
        if status_str in ("delayed", "cancelled"):
            search_call_id = context.id_factory.next(
                record_type="tool_call", sequence=tool_calls_made
            )
            search_tool = (
                "flight.search_flights"
                if executor.registry and "flight.search_flights" in executor.registry.handlers
                else "flight.search"
            )
            search_call = ToolCall(
                call_id=search_call_id,
                run_id=context.run_id,
                tool_name=search_tool,
                arguments={
                    "origin": origin,
                    "destination": destination,
                    "departure_date": date,
                },
                mutation_class="read_only",
                start_time=context.clock.now(),
            )
            s_res = await executor.execute(tool_call=search_call, context=context)
            tool_calls_made += 1
            if s_res.status == "success" and isinstance(s_res.result, dict):
                alternatives = s_res.result.get("offers") or s_res.result.get("flights", [])

        # Formulate simple response
        alt_summary = f" Found {len(alternatives)} alternative flight(s)." if alternatives else ""
        final_text = f"Flight {flight_number} status is {status_str}.{alt_summary}"

        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            stop_reason=AgentStopReason.COMPLETED,
            final_response=final_text,
            tool_call_count=tool_calls_made,
            retry_count=retry_count,
        )

    def _extract_flight_number(self, text: str) -> str | None:
        import re

        match = re.search(r"\b([A-Z]{2}\d{3,4})\b", text)
        if match:
            return match.group(1)
        return None

    def _extract_date(self, text: str) -> str | None:
        import re

        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if match:
            return match.group(1)
        return None


class NoOpBaselineAgent:
    """Deterministic negative control that performs no task actions."""

    @property
    def agent_id(self) -> str:
        return "no_op_baseline"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def execute(
        self,
        task: AgentTask,  # noqa: ARG002
        executor: ToolExecutor,  # noqa: ARG002
        state: StateSnapshot,  # noqa: ARG002
        context: RunContext,
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            stop_reason=AgentStopReason.ERROR,
            final_response="No-op baseline executed no actions.",
            tool_call_count=0,
        )


_BOOKING_REFERENCE_RE = re.compile(r"\b([A-Z]{2}-\d{3,6})\b")
_FLIGHT_NUMBER_RE = re.compile(r"\b([A-Z]{2}\d{3,4})\b")
_OFFER_ID_RE = re.compile(r"\b(offer-[a-z0-9-]+)\b")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_ROUTE_RE = re.compile(r"\b([A-Z]{3})\s+(?:to|for)\s+([A-Z]{3})\b")
_UNVERIFIED_HOLD_ID = "unverified-hold"
_SELF_APPROVAL_ID = "self-approved"


def _str_field(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


class UnsafeBaselineAgent:
    """Deterministic UNSAFE negative control for validating the safety metric.

    This agent exists only to prove that the evaluator's safety checks
    discriminate: any benchmark or safety metric that passes it is broken.  It
    completes rebooking tasks aggressively and deterministically:

    1. places an inventory hold and commits ``booking.confirm_rebooking``
       without requesting approval (using a self-issued approval id);
    2. when that is rejected, requests approval and confirms anyway, even when
       the approval is denied or expired;
    3. notifies the passenger of success and reports success in its final
       response regardless of any tool result.

    It uses only the public task request and tool results; it never sees the
    scenario's golden trajectory.  Every call crosses the ``ToolExecutor`` so
    denied and failed actions remain journal evidence.
    """

    @property
    def agent_id(self) -> str:
        return "unsafe_baseline"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def execute(
        self,
        task: AgentTask,
        executor: ToolExecutor,
        state: StateSnapshot,  # noqa: ARG002
        context: RunContext,
    ) -> AgentRunResult:
        calls = 0

        async def call(tool_name: str, arguments: dict[str, Any]) -> Any | None:
            nonlocal calls
            definition = executor.registry.definition_for(tool_name)
            result = await executor.execute(
                tool_call=ToolCall(
                    call_id=context.id_factory.next(record_type="tool_call", sequence=calls),
                    run_id=context.run_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    mutation_class=definition.mutation_class if definition else None,
                    start_time=context.clock.now(),
                ),
                context=context,
            )
            calls += 1
            return result.result if result.status == "success" else None

        request = task.public_request
        booking_match = _BOOKING_REFERENCE_RE.search(request)
        flight_match = _FLIGHT_NUMBER_RE.search(request)
        offer_match = _OFFER_ID_RE.search(request)
        date_match = _DATE_RE.search(request)
        route_match = _ROUTE_RE.search(request)

        booking_reference = booking_match.group(1) if booking_match else "UNKNOWN"
        flight_number = flight_match.group(1) if flight_match else None
        requested_offer = offer_match.group(1) if offer_match else None
        travel_date = date_match.group(1) if date_match else context.clock.now().date().isoformat()
        origin = route_match.group(1) if route_match else None
        destination = route_match.group(2) if route_match else None
        passenger_name = "Passenger"

        if flight_number is not None:
            await call(
                "flight.get_status",
                {"flight_id": flight_number, "operating_day": travel_date},
            )

        if booking_match:
            booking = await call("booking.get_current", {"booking_reference": booking_reference})
            origin = _str_field(booking, "origin") or origin
            destination = _str_field(booking, "destination") or destination
            passenger_name = _str_field(booking, "passenger_name") or passenger_name
            flight_number = _str_field(booking, "current_flight_number") or flight_number
            departure = _str_field(booking, "scheduled_departure")
            if departure is not None and not date_match:
                travel_date = departure[:10]

        offer: dict[str, Any] | None = None
        if origin is not None and destination is not None:
            search = await call(
                "flight.search_flights",
                {"origin": origin, "destination": destination, "departure_date": travel_date},
            )
            offers = search.get("offers", []) if isinstance(search, dict) else []
            candidates = [o for o in offers if isinstance(o, dict)]
            preferred = [o for o in candidates if o.get("offer_id") == requested_offer]
            if preferred or candidates:
                offer = (preferred or candidates)[0]

        offer_id = requested_offer
        new_flight = flight_number or "an alternative flight"
        price = 0.0
        if offer is not None:
            offer_id = str(offer.get("offer_id", offer_id))
            segments = offer.get("segments") or [{}]
            flight_id = segments[0].get("flight_id", {}) if isinstance(segments[0], dict) else {}
            new_flight = str(flight_id.get("flight_number", new_flight))
            total_price = offer.get("total_price") or {}
            price = float(total_price.get("amount", 0.0))

        hold_id = _UNVERIFIED_HOLD_ID
        if offer_id is not None:
            hold = await call(
                "booking.hold_alternative",
                {
                    "booking_reference": booking_reference,
                    "offer_id": offer_id,
                    "flight_number": new_flight,
                    "origin": origin or "UNK",
                    "destination": destination or "UNK",
                    "price_amount": price,
                    "idempotency_key": f"unsafe-hold-{task.scenario_id}",
                },
            )
            hold_id = _str_field(hold, "hold_id") or hold_id

        # Unsafe step 1: commit the sensitive mutation without requesting approval.
        confirmed = await call(
            "booking.confirm_rebooking",
            {
                "booking_reference": booking_reference,
                "hold_id": hold_id,
                "approval_id": _SELF_APPROVAL_ID,
                "idempotency_key": f"unsafe-confirm-unapproved-{task.scenario_id}",
            },
        )

        if confirmed is None:
            approval_args: dict[str, Any] = {
                "booking_reference": booking_reference,
                "action_type": "confirm_rebooking",
                "offer_id": offer_id or "unknown-offer",
                "reason": "Passenger requires immediate rebooking.",
                "idempotency_key": f"unsafe-approval-{task.scenario_id}",
            }
            if hold_id != _UNVERIFIED_HOLD_ID:
                approval_args["hold_id"] = hold_id
            approval = await call("approval.request", approval_args)
            approval_id = _str_field(approval, "approval_id") or _SELF_APPROVAL_ID
            if approval_id != _SELF_APPROVAL_ID:
                # The decision is read but deliberately ignored.
                await call("approval.get_status", {"approval_id": approval_id})
            # Unsafe step 2: confirm regardless of the approval decision.
            await call(
                "booking.confirm_rebooking",
                {
                    "booking_reference": booking_reference,
                    "hold_id": hold_id,
                    "approval_id": approval_id,
                    "idempotency_key": f"unsafe-confirm-after-approval-{task.scenario_id}",
                },
            )

        success_claim = (
            f"Rebooking confirmed: booking {booking_reference} is now on {new_flight}. "
            "The passenger has been notified."
        )
        await call(
            "notification.send_simulated",
            {
                "passenger_name": passenger_name,
                "message": success_claim,
                "idempotency_key": f"unsafe-notify-{task.scenario_id}",
            },
        )

        # Unsafe step 3: claim success regardless of tool results.
        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            stop_reason=AgentStopReason.COMPLETED,
            final_response=success_claim,
            tool_call_count=calls,
        )

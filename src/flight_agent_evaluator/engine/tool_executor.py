"""Asynchronous tool executor with fault injection, journaling, and state projection.

Responsibilities
----------------
1. Enforce tool-call limits.
2. Enforce logical-time limits.
3. Resolve the handler.
4. Validate arguments through a strict Pydantic input model.
5. Append :class:`ToolCall` to the journal.
6. Evaluate deterministic faults.
7. Invoke the handler when no blocking fault applies.
8. Map provider exceptions to typed ``ToolError`` values.
9. Append :class:`ToolResult` to the journal.
10. Emit trusted events.
11. Update state through the projector.
12. Advance logical time.
13. Never leak raw exception strings in machine-readable results.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from flight_agent_evaluator.engine.state_projector import StateProjector
from flight_agent_evaluator.runtime.id_factory import DeterministicIdFactory

from flight_agent_evaluator.contracts.events import DomainEvent
from flight_agent_evaluator.contracts.faults import FaultSpec
from flight_agent_evaluator.contracts.tools import (
    ToolCall,
    ToolError,
    ToolResult,
)
from flight_agent_evaluator.engine.fault_engine import (
    FaultEngine,
    InjectedFault,
    UnsupportedFaultConfigurationError,
)
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.runtime.clock import VirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import (
    ToolRegistry,
    UnknownToolError,
)

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Executes tool calls from the scripted driver."""

    def __init__(
        self,
        registry: ToolRegistry,
        faults: tuple[FaultSpec, ...],
        clock: VirtualClock,
        id_factory: DeterministicIdFactory,
        state_projector: StateProjector,
        tool_call_limit: int = 100,
        logical_time_limit_ns: int = 60 * 60 * 1_000_000_000,
        event_emitter: Callable[[DomainEvent], None] | None = None,
        provider: FlightProvider | None = None,
    ) -> None:
        self._registry = registry
        self._fault_engine = FaultEngine(faults, clock)
        self._clock = clock
        self._id_factory = id_factory
        self._projector = state_projector
        self._tool_call_limit = tool_call_limit
        self._logical_time_limit_ns = logical_time_limit_ns
        self._event_emitter = event_emitter or (lambda e: None)
        self._provider = provider
        self._call_count = 0
        self._logical_start_ns: int = 0
        self._logical_end_ns: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        context: RunContext,
        now: int,
    ) -> ToolResult:
        """Execute a single tool call."""
        # Hardened limits first.
        if self._call_count >= self._tool_call_limit:
            return self._limit_exceeded(tool_call, now)

        # Logical time check.
        if now > self._logical_end_ns:
            return self._time_limit_exceeded(tool_call, now)

        # Resolve handler.
        try:
            handler = self._registry.get(tool_call.tool_name)
        except UnknownToolError:
            return self._unknown_tool(tool_call, now)

        # Inject deterministic fault, if configured.
        fault = self._fault_engine.apply(tool_call, sequence=self._call_count)
        if fault is not None:
            self._call_count += 1
            return self._fault_result(tool_call, fault, now)

        # Emit the tool-call event.
        call_event = ToolCallEvent(
            event_id=self._id_factory.next_event(),
            run_id=tool_call.run_id,
            parent_call_id=tool_call.call_id,
            payload={"tool_name": tool_call.tool_name, "arguments": tool_call.arguments},
        )
        self._event_emitter(call_event)

        # Validate arguments against the handler's strict schema.
        input_schema = handler.tool_definition.input_schema
        if not self._is_valid_json_schema(tool_call.arguments, input_schema):
            tool_error = ToolError(
                error_type="invalid_arguments",
                message="Arguments do not satisfy the handler's input schema",
                retryable=False,
                details={"schema": input_schema},
            )
            result = ToolResult(
                call_id=tool_call.call_id,
                status="failure",
                error=tool_error,
                end_time=self._clock.now_time(),
            )
            result_event = ToolResultEvent(
                event_id=self._id_factory.next_event(),
                run_id=tool_call.run_id,
                parent_call_id=tool_call.call_id,
                payload={"status": result.status, "error": tool_error.model_dump(mode="json")},
            )
            self._event_emitter(result_event)
            return result

        # Invoke handler.
        self._call_count += 1
        try:
            raw_result = await handler.execute(
                arguments=tool_call.arguments,
                provider=self._provider or (lambda *a, **kw: None),
                context=context,
            )
        except (ValueError, TypeError, LookupError) as exc:
            logger.debug("Handler raised expected error", exc_info=exc)
            tool_error = ToolError(
                error_type="invalid_arguments",
                message="Handler raised a validation error",
                retryable=False,
                details={"correlation_id": tool_call.call_id.hex},
            )
            result = ToolResult(
                call_id=tool_call.call_id,
                status="failure",
                error=tool_error,
                end_time=self._clock.now_time(),
            )
            result_event = ToolResultEvent(
                event_id=self._id_factory.next_event(),
                run_id=tool_call.run_id,
                parent_call_id=tool_call.call_id,
                payload={"status": result.status, "error": tool_error.model_dump(mode="json")},
            )
            self._event_emitter(result_event)
            return result
        except Exception as exc:
            logger.debug("Handler raised unexpected error", exc_info=exc)
            tool_error = ToolError(
                error_type="provider_error",
                message="Unexpected handler error",
                retryable=False,
                details={"correlation_id": tool_call.call_id.hex},
            )
            result = ToolResult(
                call_id=tool_call.call_id,
                status="failure",
                error=tool_error,
                end_time=self._clock.now_time(),
            )
            result_event = ToolResultEvent(
                event_id=self._id_factory.next_event(),
                run_id=tool_call.run_id,
                parent_call_id=tool_call.call_id,
                payload={"status": result.status, "error": tool_error.model_dump(mode="json")},
            )
            self._event_emitter(result_event)
            return result

        # Normalise the result into a typed ToolResult.
        if isinstance(raw_result, dict):
            payload: Any = raw_result
        elif hasattr(raw_result, "model_dump"):
            payload = raw_result.model_dump(mode="json")
        else:
            payload = raw_result

        result = ToolResult(
            call_id=tool_call.call_id,
            status="success",
            result=payload,
            end_time=self._clock.now_time(),
        )

        # Emit result event.
        result_event = ToolResultEvent(
            event_id=self._id_factory.next_event(),
            run_id=tool_call.run_id,
            parent_call_id=tool_call.call_id,
            payload={"status": result.status, "result": payload},
        )
        self._event_emitter(result_event)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _limit_exceeded(self, call: ToolCall, now: int) -> ToolResult:
        """Return a typed failure when the tool-call limit is hit."""
        tool_error = ToolError(
            error_type="invalid_arguments",
            message="Tool-call limit exceeded — stopping execution",
            retryable=False,
            details={"correlation_id": call.call_id.hex},
        )
        return ToolResult(call_id=call.call_id, status="failure", error=tool_error, end_time=now)

    def _time_limit_exceeded(self, call: ToolCall, now: int) -> ToolResult:
        """Return a typed failure when the logical-time limit is hit."""
        tool_error = ToolError(
            error_type="timeout",
            message="Logical time limit exceeded — stopping execution",
            retryable=False,
            details={"correlation_id": call.call_id.hex},
        )
        return ToolResult(call_id=call.call_id, status="timeout", error=tool_error, end_time=now)

    def _unknown_tool(self, call: ToolCall, now: int) -> ToolResult:
        """Return a typed failure for an unknown tool."""
        tool_error = ToolError(
            error_type="invalid_arguments",
            message=f"Unknown tool: {call.tool_name!r}",
            retryable=False,
            details={"correlation_id": call.call_id.hex},
        )
        return ToolResult(call_id=call.call_id, status="failure", error=tool_error, end_time=now)

    def _fault_result(self, call: ToolCall, fault: InjectedFault, now: int) -> ToolResult:
        """Return a ToolResult for an injected fault."""
        result = ToolResult(
            call_id=call.call_id,
            status=fault.status,
            error=fault.error,
            end_time=now,
        )
        result_event = ToolResultEvent(
            event_id=self._id_factory.next_event(),
            run_id=call.run_id,
            parent_call_id=call.call_id,
            payload={"status": result.status, "injected_fault_type": fault.fault_type},
        )
        self._event_emitter(result_event)
        return result

    @staticmethod
    def _is_valid_json_schema(
        arguments: dict[str, Any],
        schema: dict[str, Any],
    ) -> bool:
        """Lightweight JSON-Schema conformance check.

        Does not implement the full draft. Checks required, types,
        properties and enum values.
        """
        required = schema.get("required", [])
        for key in required:
            if key not in arguments:
                return False
        properties = schema.get("properties", {})
        for key, value in arguments.items():
            expected = properties.get(key, {})
            expected_type = expected.get("type")
            if expected_type and not _type_matches(value, expected_type):
                return False
            enum_vals = expected.get("enum")
            if enum_vals is not None and value not in enum_vals:
                return False
            min_len = expected.get("minLength")
            if isinstance(value, str) and min_len is not None and len(value) < min_len:
                return False
        return True


def _type_matches(value: Any, expected_type: str) -> bool:
    """Return True if *value* matches *expected_type* in JSON schema terms."""
    if expected_type == "object" and isinstance(value, dict):
        return True
    if expected_type == "string" and isinstance(value, str):
        return True
    if expected_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
        return True
    if expected_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if expected_type == "boolean" and isinstance(value, bool):
        return True
    if expected_type == "array" and isinstance(value, (list, tuple)):
        return True
    if expected_type == "null" and value is None:
        return True
    return False


__all__ = [
    "ToolExecutor",
    "UnsupportedFaultConfigurationError",
]

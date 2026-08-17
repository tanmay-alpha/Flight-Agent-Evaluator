"""Asynchronous tool executor with fault injection, journaling, and state projection.

Responsibilities
----------------
1. Enforce tool-call limits.
2. Enforce logical-time limits.
3. Resolve the handler.
4. Validate arguments through a strict JSON-schema input model.
5. Append a :class:`ToolCall` journal entry.
6. Evaluate deterministic faults and append a ``fault_injected`` entry
   when one fires.
7. Invoke the handler when no blocking fault applies.
8. Map provider exceptions to typed ``ToolError`` values.
9. Append a :class:`ToolResult` journal entry.
10. Emit a domain event summary.
11. Advance logical time.
12. Update state via an immutable projector.
13. Never leak raw exception strings or credential text in
    machine-readable results.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from flight_agent_evaluator.contracts.faults import FaultSpec
from flight_agent_evaluator.contracts.tools import (
    ToolCall,
    ToolError,
    ToolResult,
)
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.fault_engine import (
    FaultEngine,
    InjectedFault,
    UnsupportedFaultConfigurationError,
)
from flight_agent_evaluator.environment.errors import (
    AmbiguousCommitError,
    ApprovalExpiredError,
    ApprovalMissingError,
    ApprovalScopeMismatchError,
    EnvironmentError,
    HoldExpiredError,
    IdempotencyConflictError,
    OfferUnavailableError,
    OwnershipMismatchError,
    ResourceNotFoundError,
    StateTransitionError,
    TransactionConflictError,
    UnknownOfferError,
)
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.recording.contracts import JournalEntry
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import VirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.tools.base import (
    ToolRegistry,
    UnknownToolError,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class StateProjector(Protocol):
    """Immutable state projection protocol."""

    def apply(self, old_state: Any, trusted_record: dict[str, Any]) -> Any:
        """Return a new state given *old_state* and a trusted *trusted_record*."""


class _IdentityProjector:
    """Default projector that records tool-call summaries into state."""

    def apply(self, old_state: Any, trusted_record: dict[str, Any]) -> Any:
        try:
            from flight_agent_evaluator.runtime.state import StateSnapshot
        except ImportError:
            return old_state
        if not isinstance(old_state, StateSnapshot):
            return old_state
        records = list(old_state.data.get("tool_call_summaries", []))
        records.append(trusted_record)
        return old_state.with_data({"tool_call_summaries": records})


class ToolExecutor:
    """Executes tool calls from the scripted driver.

    The executor journals every call, result, and injected fault. It is
    safe to use from a synchronous caller via ``asyncio.run``; the CLI
    is responsible for that boundary.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        faults: tuple[FaultSpec, ...] | FaultEngine = (),
        clock: VirtualClock | None = None,
        id_factory: DeterministicIdFactory | None = None,
        journal: HashChainJournal | None = None,
        state_projector: StateProjector | None = None,
        tool_call_limit: int = 100,
        logical_time_limit_ns: int = 60 * 60 * 1_000_000_000,
        provider: FlightProvider | None = None,
        execution_policy: ExecutionToolPolicy | None = None,
    ) -> None:
        self._registry = registry
        if isinstance(faults, FaultEngine):
            self._fault_engine = faults
        else:
            self._fault_engine = FaultEngine(faults, clock)
        self._clock = clock
        self._id_factory = id_factory
        self._journal = journal
        self._projector: Any = state_projector or _IdentityProjector()
        self._tool_call_limit = tool_call_limit
        self._logical_time_limit_ns = logical_time_limit_ns
        self._start_ns = int(clock.now().timestamp() * 1_000_000_000) if clock is not None else 0
        self._provider = provider
        self._execution_policy = execution_policy
        self._call_count = 0
        self._mutation_count = 0
        self._event_emitter: Callable[[dict[str, Any]], None] | None = None

    @property
    def registry(self) -> ToolRegistry:
        """Return the tool registry configured for this executor."""
        return self._registry

    @property
    def call_count(self) -> int:
        """Number of tool calls attempted (including failed/limit-exceeded)."""
        return self._call_count

    @property
    def execution_policy(self) -> ExecutionToolPolicy | None:
        """Return the trusted policy used at the final execution boundary."""
        return self._execution_policy

    def set_execution_policy(self, policy: ExecutionToolPolicy) -> None:
        """Install a scenario-owned policy once; it can never be broadened."""
        if self._execution_policy is None:
            self._execution_policy = policy
        elif self._execution_policy != policy:
            raise ValueError("Execution policy is immutable once installed")

    def set_event_emitter(self, emitter: Callable[[dict[str, Any]], None] | None) -> None:
        """Override the default event emitter (used by tests)."""
        self._event_emitter = emitter

    async def execute(
        self,
        tool_call: ToolCall,
        *,
        context: RunContext,
        provider: FlightProvider | None = None,
    ) -> ToolResult:
        """Execute a single tool call.

        The executor journals the call before invoking the handler, then
        journals the result. Failed calls (validation errors, faults,
        handler exceptions, limit-exceeded) are journalled as
        ``tool_result`` with a typed ``ToolError``.
        """
        now_dt = self._clock.now() if self._clock else tool_call.start_time

        # 1. Tool-call limit (always counts the attempt).
        if self._call_count >= self._tool_call_limit:
            definition = self._registry.definition_for(tool_call.tool_name)
            self._journal_tool_call(
                tool_call,
                context,
                now_dt,
                mutation_class=definition.mutation_class if definition else None,
                authorization_decision="denied",
            )
            self._call_count += 1
            return self._handler_error(
                tool_call,
                error_type="invalid_arguments",
                message="Tool-call limit exceeded — stopping execution",
                now_dt=now_dt,
                context=context,
            )

        # 2. Resolve the registry definition before writing trusted journal metadata.
        try:
            handler = self._registry.get(tool_call.tool_name)
        except UnknownToolError:
            self._call_count += 1
            self._journal_tool_call(
                tool_call, context, now_dt, mutation_class=None, authorization_decision="denied"
            )
            return self._authorization_denied(
                tool_call, now_dt, context, "Unknown or unregistered tool requested"
            )

        authoritative_class = handler.tool_definition.mutation_class
        denial: str | None = None
        if tool_call.mutation_class is not None and tool_call.mutation_class != authoritative_class:
            denial = "Caller mutation metadata conflicts with registry definition"
        elif self._execution_policy is None:
            denial = "No trusted scenario execution policy is installed"
        else:
            if self._execution_policy.scenario_id != context.scenario_id:
                denial = "Execution policy does not belong to this scenario"
            elif not self._execution_policy.permits_tool(tool_call.tool_name):
                denial = "Tool is not authorized by the scenario execution policy"
            elif not self._execution_policy.permits_mutation_class(authoritative_class):
                denial = "Tool mutation class is not authorized by the scenario execution policy"
            elif (
                authoritative_class != "read_only"
                and self._mutation_count >= self._execution_policy.maximum_mutations
            ):
                denial = "Scenario mutation limit has been reached"

        self._journal_tool_call(
            tool_call,
            context,
            now_dt,
            mutation_class=authoritative_class,
            authorization_decision="denied" if denial else "allowed",
        )
        if denial is not None:
            self._call_count += 1
            return self._authorization_denied(tool_call, now_dt, context, denial)

        # 3. Logical-time limit check.
        if self._clock is not None:
            now_ns = int(now_dt.timestamp() * 1_000_000_000)
            if (now_ns - self._start_ns) > self._logical_time_limit_ns:
                self._call_count += 1
                return self._time_limit_exceeded(tool_call, now_dt)

        # 4. Fault injection.
        fault = self._fault_engine.apply(tool_call, sequence=self._call_count)
        if fault is not None:
            if fault.fault_type == "delayed_response":
                self._journal_event(
                    entry_type="fault_injected",
                    run_id=context.run_id,
                    correlation_id=context.correlation_id,
                    time=now_dt,
                    payload={
                        "call_id": tool_call.call_id.hex,
                        "fault_type": fault.fault_type,
                        "fault_id": fault.fault_id.hex,
                        "delay_seconds": fault.delay_seconds,
                    },
                )
                if self._clock and fault.delay_seconds > 0:
                    self._clock.advance(fault.delay_seconds)
                    now_dt = self._clock.now()
            elif fault.fault_type == "duplicate_event":
                self._journal_event(
                    entry_type="fault_injected",
                    run_id=context.run_id,
                    correlation_id=context.correlation_id,
                    time=now_dt,
                    payload={
                        "call_id": tool_call.call_id.hex,
                        "fault_type": fault.fault_type,
                        "fault_id": fault.fault_id.hex,
                        "duplication_count": fault.duplication_count,
                    },
                )
            else:
                self._call_count += 1
                return self._fault_result(tool_call, fault, now_dt, context)

        # 5. Validate arguments against the handler's input schema.
        input_schema = handler.tool_definition.input_schema
        if not _validate_arguments(tool_call.arguments, input_schema):
            self._call_count += 1
            return self._invalid_arguments(tool_call, input_schema, now_dt, context)

        # 6. Invoke handler.
        self._call_count += 1
        effective_provider = provider or self._provider
        try:
            if effective_provider is None:
                return self._handler_error(
                    tool_call,
                    error_type="internal_error",
                    message="No provider configured for tool execution",
                    now_dt=now_dt,
                    context=context,
                )
            raw_result = await handler.execute(
                arguments=tool_call.arguments,
                provider=effective_provider,
                context=context,
            )
        except UnsupportedFaultConfigurationError:
            raise
        except EnvironmentError as exc:
            logger.debug("Handler raised expected environment error", exc_info=exc)
            error_type, retryable = _environment_error_details(exc)
            return self._handler_error(
                tool_call,
                error_type=error_type,
                message=_safe_environment_message(error_type),
                now_dt=now_dt,
                context=context,
                retryable=retryable,
            )
        except (ValueError, TypeError, LookupError) as exc:
            logger.debug("Handler raised expected error", exc_info=exc)
            return self._handler_error(
                tool_call,
                error_type="invalid_arguments",
                message="Handler raised a validation error",
                now_dt=now_dt,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001 - catch-all narrowed below
            logger.debug("Handler raised unexpected error", exc_info=exc)
            return self._handler_error(
                tool_call,
                error_type="internal_error",
                message="Handler raised an unexpected error",
                now_dt=now_dt,
                context=context,
            )

        # 8. Normalise the result.
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
            end_time=now_dt,
        )
        self._journal_event(
            entry_type="tool_result",
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            time=now_dt,
            payload={
                "call_id": tool_call.call_id.hex,
                "status": result.status,
                "result": payload,
            },
        )
        if authoritative_class != "read_only":
            self._mutation_count += 1
        if fault is not None and fault.fault_type == "duplicate_event":
            for _ in range(fault.duplication_count):
                self._journal_event(
                    entry_type="domain_event",
                    run_id=context.run_id,
                    correlation_id=context.correlation_id,
                    time=now_dt,
                    payload={
                        "call_id": tool_call.call_id.hex,
                        "event_type": "duplicated_event",
                        "tool_name": tool_call.tool_name,
                        "result": payload,
                    },
                )

        self._project_state({"call_id": tool_call.call_id.hex, "status": "success"})
        return result

    # ------------------------------------------------------------------
    # Failure helpers
    # ------------------------------------------------------------------

    def _limit_exceeded(self, call: ToolCall, now_dt: Any) -> ToolResult:
        tool_error = ToolError(
            error_type="invalid_arguments",
            message="Tool-call limit exceeded — stopping execution",
            retryable=False,
            details={"correlation_id": call.call_id.hex},
        )
        return ToolResult(call_id=call.call_id, status="failure", error=tool_error, end_time=now_dt)

    def _time_limit_exceeded(self, call: ToolCall, now_dt: Any) -> ToolResult:
        tool_error = ToolError(
            error_type="timeout",
            message="Logical time limit exceeded — stopping execution",
            retryable=False,
            details={"correlation_id": call.call_id.hex},
        )
        return ToolResult(call_id=call.call_id, status="timeout", error=tool_error, end_time=now_dt)

    def _authorization_denied(
        self,
        call: ToolCall,
        now_dt: Any,
        context: RunContext,
        message: str,
    ) -> ToolResult:
        """Record a blocked request as trusted evaluator evidence."""
        tool_error = ToolError(
            error_type="authorization_error",
            message=message,
            retryable=False,
            details={"correlation_id": call.call_id.hex, "tool_name": call.tool_name},
        )
        result = ToolResult(
            call_id=call.call_id,
            status="failure",
            error=tool_error,
            end_time=now_dt,
        )
        self._journal_event(
            entry_type="tool_result",
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            time=now_dt,
            payload={
                "call_id": call.call_id.hex,
                "status": result.status,
                "error": tool_error.model_dump(mode="json"),
            },
        )
        self._project_state({"call_id": call.call_id.hex, "status": "authorization_denied"})
        return result

    def _invalid_arguments(
        self,
        call: ToolCall,
        _schema: dict[str, Any],
        now_dt: Any,
        context: RunContext,
    ) -> ToolResult:
        tool_error = ToolError(
            error_type="invalid_arguments",
            message="Arguments do not satisfy the handler's input schema",
            retryable=False,
            details={"correlation_id": call.call_id.hex},
        )
        result = ToolResult(
            call_id=call.call_id,
            status="failure",
            error=tool_error,
            end_time=now_dt,
        )
        self._journal_event(
            entry_type="tool_result",
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            time=now_dt,
            payload={
                "call_id": call.call_id.hex,
                "status": result.status,
                "error": tool_error.model_dump(mode="json"),
            },
        )
        self._project_state({"call_id": call.call_id.hex, "status": "invalid_args"})
        return result

    def _handler_error(
        self,
        call: ToolCall,
        *,
        error_type: str,
        message: str,
        now_dt: Any,
        context: RunContext,
        retryable: bool = False,
    ) -> ToolResult:
        tool_error = ToolError(
            error_type=error_type,
            message=message,
            retryable=retryable,
            details={"correlation_id": call.call_id.hex},
        )
        result = ToolResult(
            call_id=call.call_id,
            status="failure",
            error=tool_error,
            end_time=now_dt,
        )
        self._journal_event(
            entry_type="tool_result",
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            time=now_dt,
            payload={
                "call_id": call.call_id.hex,
                "status": result.status,
                "error": tool_error.model_dump(mode="json"),
            },
        )
        self._project_state({"call_id": call.call_id.hex, "status": error_type})
        return result

    def _fault_result(
        self,
        call: ToolCall,
        fault: InjectedFault,
        now_dt: Any,
        context: RunContext,
    ) -> ToolResult:
        self._journal_event(
            entry_type="fault_injected",
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            time=now_dt,
            payload={
                "call_id": call.call_id.hex,
                "fault_type": fault.fault_type,
                "fault_id": fault.fault_id.hex,
            },
        )
        result = ToolResult(
            call_id=call.call_id,
            status=fault.status,
            error=fault.error,
            end_time=now_dt,
        )
        self._journal_event(
            entry_type="tool_result",
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            time=now_dt,
            payload={
                "call_id": call.call_id.hex,
                "status": result.status,
                "error": fault.error.model_dump(mode="json") if fault.error else None,
                "injected_fault_type": fault.fault_type,
            },
        )
        self._project_state({"call_id": call.call_id.hex, "status": fault.fault_type})
        return result

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _journal_event(
        self,
        *,
        entry_type: str,
        run_id: Any,
        correlation_id: str,
        time: Any,
        payload: dict[str, Any],
    ) -> None:
        """Append an event to the configured journal, if any."""
        if self._journal is None:
            return
        # Derive a deterministic entry id from id_factory when available.
        if self._id_factory is not None:
            entry_id = self._id_factory.next(
                record_type=entry_type, sequence=self._journal.entry_count
            )
        else:
            # Fallback: derive from run_id and entry count (still deterministic).
            entry_id = uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"{run_id}|{entry_type}|{self._journal.entry_count}",
            )
        seq = self._journal.entry_count + 1
        prev_hash = self._journal.entries[-1].hash if self._journal.entries else ""
        draft = JournalEntry(
            seq=seq,
            id=entry_id,
            type=entry_type,
            run_id=run_id,
            correlation_id=correlation_id,
            time=time,
            payload=payload,
            prev_hash=prev_hash,
            hash="0" * 64,
        )
        self._journal.append(draft)

    def _journal_tool_call(
        self,
        call: ToolCall,
        context: RunContext,
        now_dt: Any,
        *,
        mutation_class: str | None,
        authorization_decision: str,
    ) -> None:
        """Journal request data separately from registry-derived truth."""
        self._journal_event(
            entry_type="tool_call",
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            time=now_dt,
            payload={
                "call_id": call.call_id.hex,
                "tool_name": call.tool_name,
                "mutation_class": mutation_class,
                "requested_mutation_class": call.mutation_class,
                "authorization_decision": authorization_decision,
                "scenario_id": context.scenario_id,
                "arguments": call.arguments,
                "timeout_seconds": call.timeout_seconds,
                "idempotency_key": call.idempotency_key,
                "approval_request_id": call.approval_request_id,
            },
        )

    def _project_state(self, _summary: dict[str, Any]) -> None:
        """Placeholder for runtime state projection."""
        return


def _validate_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Return True if *arguments* satisfies *schema*.

    Implements a strict subset of JSON Schema sufficient for the
    packaged tool schemas: required keys, declared types, enums,
    ``minLength``/``maxLength``, ``format`` hints are not enforced.
    """
    required = schema.get("required", [])
    for key in required:
        if key not in arguments:
            return False
    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    if additional is False:
        for key in arguments:
            if key not in properties:
                return False
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
        max_len = expected.get("maxLength")
        if isinstance(value, str) and max_len is not None and len(value) > max_len:
            return False
        min_val = expected.get("minimum")
        if min_val is not None and isinstance(value, (int, float)) and value < min_val:
            return False
        max_val = expected.get("maximum")
        if max_val is not None and isinstance(value, (int, float)) and value > max_val:
            return False
    return True


def _type_matches(value: Any, expected_type: str) -> bool:
    """Return True if *value* matches *expected_type* in JSON-schema terms."""
    if expected_type == "object" and isinstance(value, dict):
        return True
    if expected_type == "string" and isinstance(value, str):
        return True
    if expected_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
        return True
    if (
        expected_type == "number"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return True
    if expected_type == "boolean" and isinstance(value, bool):
        return True
    if expected_type == "array" and isinstance(value, (list, tuple)):
        return True
    return bool(expected_type == "null" and value is None)


def _environment_error_details(error: EnvironmentError) -> tuple[str, bool]:
    """Map expected domain failures to safe, actionable tool error categories."""
    if isinstance(error, OwnershipMismatchError):
        return "ownership_error", False
    if isinstance(error, ApprovalMissingError):
        return "approval_required", False
    if isinstance(error, ApprovalExpiredError):
        return "approval_expired", False
    if isinstance(error, ApprovalScopeMismatchError):
        return "approval_scope_mismatch", False
    if isinstance(error, UnknownOfferError):
        return "unknown_offer", False
    if isinstance(error, HoldExpiredError):
        return "offer_unavailable", False
    if isinstance(error, OfferUnavailableError):
        return "offer_unavailable", False
    if isinstance(error, StateTransitionError):
        return "invalid_state_transition", False
    if isinstance(error, IdempotencyConflictError):
        return "idempotency_conflict", False
    if isinstance(error, TransactionConflictError):
        return "transaction_conflict", True
    if isinstance(error, AmbiguousCommitError):
        return "ambiguous_commit", True
    if isinstance(error, ResourceNotFoundError):
        return "invalid_arguments", False
    return "internal_error", False


def _safe_environment_message(error_type: str) -> str:
    """Return a stable message without leaking raw environment internals."""
    return {
        "ownership_error": "Requested resources are outside the booking ownership scope",
        "approval_required": "Sensitive mutation requires an approved authorization",
        "approval_expired": "Approval has expired",
        "approval_scope_mismatch": "Approval does not authorize this mutation payload",
        "unknown_offer": "Requested offer is not available in the authoritative inventory",
        "offer_unavailable": "Requested hold or offer is no longer available",
        "invalid_state_transition": "Requested transaction is invalid for the current state",
        "idempotency_conflict": "Idempotency key conflicts with a different request",
        "transaction_conflict": "Transaction conflicts with current environment state",
        "ambiguous_commit": "Mutation committed but the response was lost; retry with the same idempotency key",
    }.get(error_type, "Environment rejected the requested operation")


__all__ = [
    "StateProjector",
    "ToolExecutor",
    "UnsupportedFaultConfigurationError",
]

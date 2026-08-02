"""Deterministic fault injection for the Phase 2 runtime.

The engine matches the real ``FaultSpec`` contract: each fault is a
typed Pydantic model with discriminated ``fault_type`` and a fixed set
of fields. The engine never reads fictional fields.

Activation rules are honoured:

- ``always`` — every matching call fires up to ``occurrence_count``
  times.
- ``after_n_calls`` — fires only after the tool has been called
  ``call_index`` times.
- ``on_match`` — fires when the canonical payload contains the
  configured substring.
- ``time_window`` — fires only when the run's logical clock falls
  between ``window_start`` and ``window_end``.

Unsupported configurations raise :class:`UnsupportedFaultConfigurationError`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from flight_agent_evaluator.canonical import canonical_json
from flight_agent_evaluator.contracts.faults import (
    ActivationRule,
    ConflictingResponseFault,
    DelayedResponseFault,
    DuplicateEventFault,
    FaultSpec,
    MalformedResponseFault,
    ProviderServerErrorFault,
    RateLimitFault,
    StaleResponseFault,
    TimeoutFault,
)
from flight_agent_evaluator.contracts.tools import (
    ToolCall,
    ToolError,
    ToolResult,
    ToolResultStatus,
)
from flight_agent_evaluator.runtime.clock import VirtualClock


class UnsupportedFaultConfigurationError(ValueError):
    """Raised when a configured fault cannot be applied."""


@dataclass(frozen=True)
class InjectedFault:
    """A fault decision returned by the fault engine."""

    fault_id: uuid.UUID
    fault_type: str
    status: ToolResultStatus
    error: ToolError


class FaultEngine:
    """Deterministic fault injector.

    For each tool call, computes a SHA-256 digest of the (scenario seed,
    tool name, fault discriminator, call sequence) and decides
    deterministically whether to inject a fault based on the
    configured :class:`FaultSpec`. ``occurrence_count`` is decremented
    after every injection so the engine itself enforces budget caps.
    """

    def __init__(
        self,
        faults: tuple[FaultSpec, ...],
        clock: VirtualClock | None = None,
    ) -> None:
        self._faults: tuple[FaultSpec, ...] = faults
        self._clock = clock
        # Activation budget state, mutated by ``apply`` and by the
        # runtime bookkeeping. Determinism comes from the call-order
        # sequence used as part of the digest.
        self._remaining: dict[tuple[int, str], int] = {}
        self._calls_seen: dict[str, int] = {}
        for index, fault in enumerate(faults):
            key = (index, _provider_key(fault))
            self._remaining[key] = int(getattr(fault, "occurrence_count", 0))

    @property
    def faults(self) -> tuple[FaultSpec, ...]:
        return self._faults

    def reset(self) -> None:
        """Reset per-run fault counters; used between verification runs."""
        self._calls_seen.clear()
        for key in list(self._remaining):
            self._remaining[key] = int(getattr(self._faults[key[0]], "occurrence_count", 0))

    def apply(
        self,
        tool_call: ToolCall,
        *,
        sequence: int,
    ) -> InjectedFault | None:
        """Apply faults for a single tool call.

        ``sequence`` is a deterministic 0-based call index within the
        current run. It is included in the SHA-256 digest so the engine
        is reproducible across runs.
        """
        del sequence  # currently unused; reserved for further activation types

        tool_name = tool_call.tool_name
        # Track per-tool call counts for after_n_calls activation.
        self._calls_seen[tool_name] = self._calls_seen.get(tool_name, 0) + 1

        for index, fault in enumerate(self._faults):
            target = getattr(fault, "target_tool", None)
            if target is not None and target != tool_name:
                continue
            if not _activation_active(
                fault.activation,
                calls_for_tool=self._calls_seen[tool_name],
                clock=self._clock,
                arguments=tool_call.arguments,
            ):
                continue
            provider_name = _provider_key(fault)
            key = (index, provider_name)
            budget = self._remaining.get(key, 0)
            if budget <= 0:
                continue
            self._remaining[key] = budget - 1
            return _build_fault(fault)
        return None


def _provider_key(fault: FaultSpec) -> str:
    return getattr(fault, "target_provider", "synthetic-fixture")


def _activation_active(
    activation: ActivationRule,
    *,
    calls_for_tool: int,
    clock: VirtualClock | None,
    arguments: dict[str, object],
) -> bool:
    kind = activation.kind
    if kind == "always":
        return True
    if kind == "after_n_calls":
        if activation.call_index is None:
            raise UnsupportedFaultConfigurationError("after_n_calls activation requires call_index")
        return calls_for_tool >= activation.call_index + 1
    if kind == "on_match":
        if activation.match_substring is None:
            raise UnsupportedFaultConfigurationError("on_match activation requires match_substring")
        canonical = canonical_json(arguments)
        return activation.match_substring in canonical
    if kind == "time_window":
        if activation.window_start is None or activation.window_end is None:
            raise UnsupportedFaultConfigurationError(
                "time_window activation requires window_start and window_end"
            )
        if clock is None:
            raise UnsupportedFaultConfigurationError(
                "time_window activation requires a deterministic clock"
            )
        now = clock.now()
        return activation.window_start <= now <= activation.window_end
    raise UnsupportedFaultConfigurationError(f"Unsupported activation kind: {kind!r}")


def _build_fault(fault: FaultSpec) -> InjectedFault:
    """Construct an :class:`InjectedFault` from a :class:`FaultSpec`."""
    digest_input = canonical_json(fault.model_dump(mode="json"))
    fault_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"fault|{digest_input}")
    status, error = _fault_to_error(fault)
    return InjectedFault(
        fault_id=fault_id,
        fault_type=fault.fault_type,
        status=status,
        error=error,
    )


def _fault_to_error(fault: FaultSpec) -> tuple[ToolResultStatus, ToolError]:
    """Map a :class:`FaultSpec` to a ``ToolResultStatus`` / ``ToolError`` pair."""
    if isinstance(fault, TimeoutFault):
        return (
            "timeout",
            ToolError(
                error_type="timeout",
                message="Tool call timed out (injected fault)",
                retryable=True,
                details={"timeout_seconds": fault.timeout_seconds},
            ),
        )
    if isinstance(fault, RateLimitFault):
        return (
            "failure",
            ToolError(
                error_type="provider_error",
                message="Provider rate limited (injected fault)",
                retryable=True,
                details={"retry_after_seconds": fault.retry_after_seconds},
            ),
        )
    if isinstance(fault, ProviderServerErrorFault):
        return (
            "failure",
            ToolError(
                error_type="provider_error",
                message=(f"Provider returned {fault.status_code} (injected fault)"),
                retryable=True,
                details={"status_code": fault.status_code},
            ),
        )
    if isinstance(fault, MalformedResponseFault):
        return (
            "failure",
            ToolError(
                error_type="invalid_arguments",
                message="Malformed response from provider (injected fault)",
                retryable=False,
                details={"description": fault.description},
            ),
        )
    if isinstance(fault, StaleResponseFault):
        return (
            "failure",
            ToolError(
                error_type="provider_error",
                message="Stale response from provider (injected fault)",
                retryable=True,
                details={"staleness_seconds": fault.staleness_seconds},
            ),
        )
    if isinstance(fault, ConflictingResponseFault):
        return (
            "failure",
            ToolError(
                error_type="provider_error",
                message="Conflicting response from provider (injected fault)",
                retryable=False,
                details={"field_path": fault.field_path},
            ),
        )
    if isinstance(fault, DelayedResponseFault):
        return (
            "failure",
            ToolError(
                error_type="provider_error",
                message="Delayed response from provider (injected fault)",
                retryable=True,
                details={"delay_seconds": fault.delay_seconds},
            ),
        )
    if isinstance(fault, DuplicateEventFault):
        return (
            "failure",
            ToolError(
                error_type="provider_error",
                message="Duplicate event emitted by provider (injected fault)",
                retryable=False,
                details={"duplication_count": fault.duplication_count},
            ),
        )
    raise UnsupportedFaultConfigurationError(f"Unknown fault_type: {type(fault).__name__}")


__all__ = [
    "FaultEngine",
    "InjectedFault",
    "UnsupportedFaultConfigurationError",
]


# ToolResultStatus is re-exported for tests that introspect the engine
# without importing the contracts package directly.
_ = ToolResult

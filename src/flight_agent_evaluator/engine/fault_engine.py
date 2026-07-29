"""Deterministic fault injection for the Phase 2 runtime.

Faults are configured per scenario and applied deterministically based on
the scenario seed and the call sequence. The engine is a pure function:

- Same scenario + same seed + same call sequence → same fault.

Supported fault types are mapped to provider/tool error types.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from flight_agent_evaluator.contracts.faults import FaultSpec
from flight_agent_evaluator.contracts.tools import ToolError, ToolResultStatus


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
    tool name, call sequence) and decides deterministically whether to
    inject a fault based on the configured FaultSpec.
    """

    def __init__(self, faults: tuple[FaultSpec, ...]) -> None:
        self._faults = faults

    @property
    def faults(self) -> tuple[FaultSpec, ...]:
        return self._faults

    def apply(
        self,
        tool_name: str,
        seed: int,
        sequence: int,
    ) -> InjectedFault | None:
        """Apply faults for a single tool call.

        Returns an ``InjectedFault`` if one was triggered; otherwise ``None``.
        The decision is deterministic for fixed inputs.
        """
        for fault in self._faults:
            if fault.tool_name != tool_name:
                continue
            if not fault.enabled:
                continue
            digest = hashlib.sha256(
                f"{seed}|{tool_name}|{sequence}|{fault.fault_id}".encode()
            ).hexdigest()
            threshold = int(digest[:8], 16) / 0xFFFFFFFF
            if threshold < fault.probability:
                return _build_fault(fault, digest)
        return None


def _build_fault(fault: FaultSpec, digest: str) -> InjectedFault:
    """Construct an ``InjectedFault`` from a ``FaultSpec``."""
    fault_id = uuid.uuid5(
        uuid.NAMESPACE_DNS, f"fault|{fault.fault_id}|{digest}"
    )
    status, error = _fault_to_error(fault)
    return InjectedFault(
        fault_id=fault_id,
        fault_type=fault.fault_type,
        status=status,
        error=error,
    )


def _fault_to_error(fault: FaultSpec) -> tuple[ToolResultStatus, ToolError]:
    """Map a ``FaultSpec`` to a status/error pair."""
    if fault.fault_type == "provider_unavailable":
        return "failure", ToolError(
            error_type="provider_error",
            message="Provider unavailable (injected fault)",
            retryable=True,
        )
    if fault.fault_type == "timeout":
        return "timeout", ToolError(
            error_type="timeout",
            message="Tool call timed out (injected fault)",
            retryable=True,
        )
    if fault.fault_type == "invalid_response":
        return "failure", ToolError(
            error_type="invalid_arguments",
            message="Invalid response from provider (injected fault)",
            retryable=False,
        )
    if fault.fault_type == "rate_limited":
        return "failure", ToolError(
            error_type="provider_error",
            message="Rate limited (injected fault)",
            retryable=True,
        )
    return "failure", ToolError(
        error_type="internal_error",
        message=f"Unknown fault type: {fault.fault_type}",
    )

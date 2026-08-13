"""Authoritative trajectory reference resolver for step dataflow.

Enables scripted drivers and oracle agents to pass outputs from earlier
successful steps into subsequent step inputs via RFC 6901 JSON Pointers.
"""

from __future__ import annotations

from typing import Any

from flight_agent_evaluator.contracts.json_pointer import MISSING, resolve_json_pointer


class TrajectoryReferenceError(ValueError):
    """Raised when a trajectory step reference cannot be resolved."""


class PriorStepRecord:
    """Record of an earlier step's execution result."""

    def __init__(
        self, step_index: int, tool_name: str, success: bool, result: dict[str, Any]
    ) -> None:
        self.step_index = step_index
        self.tool_name = tool_name
        self.success = success
        self.result = result


class TrajectoryReferenceResolver:
    """Authoritative resolver for trajectory step references.

    Supports both structured dict references:
      {"$ref_step": 0, "json_pointer": "/hold_id"}

    And inline string references:
      "$ref:0/hold_id"
    """

    def resolve_value(self, val: Any, prior_steps: list[PriorStepRecord]) -> Any:
        """Recursively resolve step references in arguments."""
        if isinstance(val, dict):
            if "$ref_step" in val and "json_pointer" in val:
                step_idx = int(val["$ref_step"])
                pointer = str(val["json_pointer"])
                return self._resolve_pointer(step_idx, pointer, prior_steps)
            return {k: self.resolve_value(v, prior_steps) for k, v in val.items()}

        if isinstance(val, str) and val.startswith("$ref:"):
            # Format: $ref:step_index/json_pointer
            raw = val[5:]
            if "/" in raw:
                parts = raw.split("/", 1)
                step_idx = int(parts[0])
                pointer = "/" + parts[1]
            else:
                step_idx = int(raw)
                pointer = ""
            return self._resolve_pointer(step_idx, pointer, prior_steps)

        if isinstance(val, list):
            return [self.resolve_value(v, prior_steps) for v in val]

        return val

    def resolve_arguments(
        self, arguments: dict[str, Any], prior_steps: list[PriorStepRecord]
    ) -> dict[str, Any]:
        """Resolve all references within an arguments dictionary."""
        resolved = self.resolve_value(arguments, prior_steps)
        if not isinstance(resolved, dict):
            raise TrajectoryReferenceError("Resolved arguments must be a dictionary")
        return resolved

    def _resolve_pointer(
        self, step_idx: int, pointer: str, prior_steps: list[PriorStepRecord]
    ) -> Any:
        if step_idx < 0 or step_idx >= len(prior_steps):
            raise TrajectoryReferenceError(
                f"Step reference index {step_idx} out of range (available prior steps: {len(prior_steps)})"
            )

        step_record = prior_steps[step_idx]
        if not step_record.success:
            raise TrajectoryReferenceError(
                f"Cannot reference failed step {step_idx} ({step_record.tool_name})"
            )

        res = resolve_json_pointer(step_record.result, pointer)
        if res is MISSING:
            raise TrajectoryReferenceError(
                f"Reference pointer '{pointer}' not found in result of step {step_idx} ({step_record.tool_name})"
            )

        return res

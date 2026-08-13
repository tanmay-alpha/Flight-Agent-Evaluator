"""Scripted agent driver for the Phase 2 runtime.

The ``ScriptedAgentDriver`` is a deterministic test double for an agent.
It reads a ``ScriptedTrajectory`` from the scenario and produces a
deterministic stream of tool calls and final responses.

This is a TEST DOUBLE for the evaluation infrastructure. Scripted
trajectories are NOT benchmark ground truth for future agent quality
measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flight_agent_evaluator.contracts.json_pointer import MISSING, resolve_json_pointer
from flight_agent_evaluator.recording.contracts import (
    InvokeToolStep,
    ProduceFinalResponseStep,
    RecordCheckpointStep,
    ScriptedTrajectory,
)
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot


@dataclass
class ScriptedDriverResult:
    """Outcome of executing a scripted trajectory."""

    tool_calls_made: int
    final_response: str | None
    checkpoints: tuple[str, ...]


def _resolve_argument_value(val: Any, prior_results: list[dict[str, Any]]) -> Any:
    if isinstance(val, dict):
        if "$ref_step" in val and "json_pointer" in val:
            step_idx = int(val["$ref_step"])
            pointer = str(val["json_pointer"])
            if step_idx < 0 or step_idx >= len(prior_results):
                raise ValueError(f"Step reference index {step_idx} out of range")
            res = resolve_json_pointer(prior_results[step_idx], pointer)
            if res is MISSING:
                raise KeyError(f"Reference '{pointer}' not found in output of step {step_idx}")
            return res
        return {k: _resolve_argument_value(v, prior_results) for k, v in val.items()}
    if isinstance(val, str) and val.startswith("$ref:"):
        # Format: $ref:step_index/json_pointer
        parts = val[5:].split("/", 1)
        step_idx = int(parts[0])
        pointer = "/" + parts[1] if len(parts) > 1 else ""
        if step_idx < 0 or step_idx >= len(prior_results):
            raise ValueError(f"Step reference index {step_idx} out of range")
        res = resolve_json_pointer(prior_results[step_idx], pointer)
        if res is MISSING:
            raise KeyError(f"Reference '{pointer}' not found in output of step {step_idx}")
        return res
    if isinstance(val, list):
        return [_resolve_argument_value(v, prior_results) for v in val]
    return val


def resolve_step_arguments(
    arguments: dict[str, Any], prior_results: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve JSON pointer references to outputs of prior trajectory steps."""
    return {k: _resolve_argument_value(v, prior_results) for k, v in arguments.items()}


class ScriptedAgentDriver:
    """Deterministic test double for an agent.

    The driver is async because the ``ToolExecutor`` it dispatches to is
    async. The driver itself contains no I/O.
    """

    async def execute(
        self,
        trajectory: ScriptedTrajectory,
        executor: Any,
        provider: Any,  # noqa: ARG002 — retained for interface compatibility
        state: StateSnapshot,
        tool_calls_remaining: int,
        context: RunContext,
    ) -> ScriptedDriverResult:
        """Execute the trajectory through the tool executor.

        Each ``invoke_tool`` step invokes the tool; ``record_checkpoint``
        records a labelled checkpoint; ``produce_final_response`` returns
        the final response string.
        """
        from flight_agent_evaluator.contracts.tools import ToolCall

        tool_calls_made = 0
        final_response: str | None = None
        checkpoints: list[str] = []
        current_state = state
        tool_calls_list: list[dict[str, object]] = []
        prior_results: list[dict[str, Any]] = []

        for step in trajectory.steps:
            if isinstance(step, InvokeToolStep):
                if tool_calls_remaining <= 0:
                    continue
                tool_call_id = context.id_factory.next(
                    record_type="tool_call", sequence=tool_calls_made
                )
                resolved_args = resolve_step_arguments(step.arguments, prior_results)
                tool_call = ToolCall(
                    call_id=tool_call_id,
                    run_id=context.run_id,
                    tool_name=step.tool_name,
                    arguments=resolved_args,
                    mutation_class="read_only",
                    start_time=context.clock.now(),
                )
                result = await executor.execute(
                    tool_call=tool_call,
                    context=context,
                )
                if result.status == "success":
                    tool_calls_made += 1
                    tool_calls_remaining -= 1
                    res_payload = result.result if isinstance(result.result, dict) else {}
                    prior_results.append(res_payload)
                    tool_calls_list.append(
                        {
                            "tool_name": step.tool_name,
                            "result": result.result,
                        }
                    )
                    current_state = current_state.with_data({"tool_calls": list(tool_calls_list)})
            elif isinstance(step, RecordCheckpointStep):
                checkpoints.append(step.label)
            elif isinstance(step, ProduceFinalResponseStep):
                final_response = step.response

        return ScriptedDriverResult(
            tool_calls_made=tool_calls_made,
            final_response=final_response,
            checkpoints=tuple(checkpoints),
        )

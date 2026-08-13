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

from flight_agent_evaluator.drivers.resolver import (
    PriorStepRecord,
    TrajectoryReferenceResolver,
)
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


def resolve_step_arguments(
    arguments: dict[str, Any], prior_results: list[dict[str, Any]] | list[PriorStepRecord]
) -> dict[str, Any]:
    """Resolve JSON pointer references to outputs of prior trajectory steps."""
    resolver = TrajectoryReferenceResolver()
    if prior_results and isinstance(prior_results[0], dict):
        prior_steps = [
            PriorStepRecord(
                step_index=idx,
                tool_name="unknown",
                success=True,
                result=res,  # type: ignore[arg-type]
            )
            for idx, res in enumerate(prior_results)
        ]
    else:
        prior_steps = prior_results  # type: ignore[assignment]
    return resolver.resolve_arguments(arguments, prior_steps)


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
        prior_steps: list[PriorStepRecord] = []
        resolver = TrajectoryReferenceResolver()

        for step in trajectory.steps:
            if isinstance(step, InvokeToolStep):
                if tool_calls_remaining <= 0:
                    continue
                tool_call_id = context.id_factory.next(
                    record_type="tool_call", sequence=tool_calls_made
                )
                resolved_args = resolver.resolve_arguments(step.arguments, prior_steps)
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
                is_success = result.status == "success"
                res_payload = (
                    result.result if isinstance(result.result, dict) else {"result": result.result}
                )
                prior_steps.append(
                    PriorStepRecord(
                        step_index=len(prior_steps),
                        tool_name=step.tool_name,
                        success=is_success,
                        result=res_payload,
                    )
                )
                if is_success:
                    tool_calls_made += 1
                    tool_calls_remaining -= 1
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

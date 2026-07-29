"""Scripted agent driver for the Phase 2 runtime.

The ``ScriptedAgentDriver`` is a deterministic test double for an agent.
It reads a ``ScriptedTrajectory`` from the scenario and produces a
deterministic stream of tool calls and final responses.

This is a TEST DOUBLE for the evaluation infrastructure. Scripted
trajectories are NOT benchmark ground truth for future agent quality
measurements.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

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


class ScriptedAgentDriver:
    """Deterministic test double for an agent."""

    def execute(
        self,
        trajectory: ScriptedTrajectory,
        executor: Any,
        provider: Any,
        state: StateSnapshot,
        tool_calls_remaining: int,
        context: RunContext,
    ) -> ScriptedDriverResult:
        """Execute the trajectory through the tool executor.

        Each ``invoke_tool`` step invokes the tool; ``record_checkpoint``
        records a labelled checkpoint; ``produce_final_response`` returns
        the final response string.
        """
        tool_calls_made = 0
        final_response: str | None = None
        checkpoints: list[str] = []

        for step in trajectory.steps:
            if isinstance(step, InvokeToolStep):
                if tool_calls_remaining <= 0:
                    continue
                tool_call_id = context.id_factory.next(
                    record_type="tool_call", sequence=tool_calls_made
                )
                from flight_agent_evaluator.contracts.tools import ToolCall

                tool_call = ToolCall(
                    call_id=uuid.UUID(int=tool_call_id.int),
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                )
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    executor.execute(
                        tool_call=tool_call,
                        provider=provider,
                        context=context,
                        journal=None,
                    )
                )
                if result.status == "success":
                    tool_calls_made += 1
                    tool_calls_remaining -= 1
                    state.data.setdefault("tool_calls", []).append(
                        {
                            "tool_name": step.tool_name,
                            "result": result.result,
                        }
                    )
            elif isinstance(step, RecordCheckpointStep):
                checkpoints.append(step.label)
            elif isinstance(step, ProduceFinalResponseStep):
                final_response = step.response

        return ScriptedDriverResult(
            tool_calls_made=tool_calls_made,
            final_response=final_response,
            checkpoints=tuple(checkpoints),
        )

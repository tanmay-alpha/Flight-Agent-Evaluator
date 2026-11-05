"""AgentPolicy that re-executes an imported trace against the trusted environment."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from flight_agent_evaluator.canonical import canonical_json
from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    AgentTask,
    ModelUsage,
)
from flight_agent_evaluator.contracts.tools import ToolCall, ToolResult
from flight_agent_evaluator.drivers.resolver import (
    PriorStepRecord,
    TrajectoryReferenceResolver,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.traces.format import AgentTrace, TraceToolCall

DivergenceKind = Literal["result_mismatch", "status_mismatch", "not_replayed"]


class TraceDivergence(BaseModel):
    """A point where the agent's claimed observation disagrees with the environment.

    ``result_mismatch``: both succeeded but payloads differ.
    ``status_mismatch``: one side succeeded and the other failed.
    ``not_replayed``: replay stopped before this call (unresolvable ``$ref``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_index: int
    tool_name: str
    kind: DivergenceKind
    environment_status: str | None
    detail: str

    def as_warning(self) -> str:
        """Render as an ``AgentRunResult.warnings`` entry."""
        return (
            f"trace_divergence[{self.kind}] call {self.call_index} ({self.tool_name}): "
            f"{self.detail}"
        )


def _to_json_value(value: Any) -> Any:
    """Normalise *value* to plain JSON types (datetimes, UUIDs, Decimals as strings)."""
    try:
        return json.loads(canonical_json(value))
    except (ValueError, TypeError):
        return repr(value)


def _compare(index: int, call: TraceToolCall, result: ToolResult) -> TraceDivergence | None:
    env_ok = result.status == "success"
    if call.observed_error is not None:
        if env_ok:
            return TraceDivergence(
                call_index=index,
                tool_name=call.tool_name,
                kind="status_mismatch",
                environment_status=result.status,
                detail="agent observed an error but the environment call succeeded",
            )
        return None
    if not call.has_observed_result:
        return None
    if not env_ok:
        reason = result.error.message if result.error else result.status
        return TraceDivergence(
            call_index=index,
            tool_name=call.tool_name,
            kind="status_mismatch",
            environment_status=result.status,
            detail=f"agent observed a result but the environment call failed: {reason}",
        )
    if _to_json_value(call.observed_result) != _to_json_value(result.result):
        return TraceDivergence(
            call_index=index,
            tool_name=call.tool_name,
            kind="result_mismatch",
            environment_status=result.status,
            detail="agent-observed result differs from the environment result",
        )
    return None


class TraceReplayPolicy:
    """Replay an imported :class:`AgentTrace` through the real ``ToolExecutor``.

    Calls are submitted in trace order with the agent's arguments; the
    environment decides authorization, faults and results, and the executor
    journals them. Agent-observed results are only compared against the
    environment's results to populate :attr:`divergences`. Every call is
    replayed even after environment failures, because the agent's decisions
    are fixed by the trace. Replay stops early only when a ``$ref`` argument
    cannot be resolved (stop reason ``error``).
    """

    def __init__(self, trace: AgentTrace) -> None:
        self._trace = trace
        self._divergences: list[TraceDivergence] = []

    @property
    def agent_id(self) -> str:
        return f"trace:{self._trace.agent.name}"

    @property
    def agent_version(self) -> str:
        return self._trace.agent.version or "unversioned"

    @property
    def divergences(self) -> list[TraceDivergence]:
        """Divergences found by the most recent :meth:`execute`."""
        return list(self._divergences)

    async def execute(
        self,
        task: AgentTask,  # noqa: ARG002
        executor: ToolExecutor,
        state: StateSnapshot,  # noqa: ARG002
        context: RunContext,
    ) -> AgentRunResult:
        divergences: list[TraceDivergence] = []
        prior_steps: list[PriorStepRecord] = []
        resolver = TrajectoryReferenceResolver()
        stop_reason = AgentStopReason.COMPLETED
        replayed = 0

        for index, call in enumerate(self._trace.calls):
            try:
                arguments = resolver.resolve_arguments(call.arguments, prior_steps)
            except (ValueError, TypeError) as exc:
                # The agent's final response is kept so its claims are still evaluated.
                stop_reason = AgentStopReason.ERROR
                divergences.extend(
                    TraceDivergence(
                        call_index=skipped,
                        tool_name=self._trace.calls[skipped].tool_name,
                        kind="not_replayed",
                        environment_status=None,
                        detail=str(exc) if skipped == index else "replay stopped earlier",
                    )
                    for skipped in range(index, len(self._trace.calls))
                )
                break

            # mutation_class is left unset: the executor resolves the
            # authoritative class from the registry, never from the trace.
            tool_call = ToolCall(
                call_id=context.id_factory.next(record_type="tool_call", sequence=index),
                run_id=context.run_id,
                tool_name=call.tool_name,
                arguments=arguments,
                start_time=context.clock.now(),
            )
            result = await executor.execute(tool_call=tool_call, context=context)
            replayed += 1

            payload = (
                result.result if isinstance(result.result, dict) else {"result": result.result}
            )
            prior_steps.append(
                PriorStepRecord(
                    step_index=index,
                    tool_name=call.tool_name,
                    success=result.status == "success",
                    result=payload,
                )
            )
            divergence = _compare(index, call, result)
            if divergence is not None:
                divergences.append(divergence)

        self._divergences = divergences
        usage = self._trace.usage
        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            stop_reason=stop_reason,
            final_response=self._trace.final_response,
            model_call_count=usage.model_calls if usage else 0,
            tool_call_count=replayed,
            usage=ModelUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
            if usage
            else ModelUsage(),
            warnings=[d.as_warning() for d in divergences],
        )


__all__ = ["DivergenceKind", "TraceDivergence", "TraceReplayPolicy"]

"""Baseline agent implementations: Scripted Oracle Agent and Naive Baseline Agent."""

from __future__ import annotations

import logging
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
            task_id=task.task_id,
            scenario_id=task.scenario_id,
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


class RandomBaselineAgent:
    """Random baseline agent for benchmark evaluation."""

    @property
    def agent_id(self) -> str:
        return "random_baseline"

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
            final_response="Random baseline execution failed.",
            tool_call_count=0,
        )

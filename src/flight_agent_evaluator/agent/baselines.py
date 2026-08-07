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

        for step in self._golden_steps:
            if step.get("type") == "final_response":
                final_response = step.get("content", "Task completed.")
                break

            tool_name = step.get("tool_name", "")
            args = step.get("arguments", {})

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
                arguments=args,
                mutation_class=mutation_class,
                start_time=context.clock.now(),
            )

            exec_result = await executor.execute(tool_call=tool_call, context=context)
            tool_calls_made += 1

            if exec_result.status == "success" and exec_result.result:
                current_state = current_state.with_data({"last_result": exec_result.result})

        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            stop_reason=AgentStopReason.COMPLETED,
            final_response=final_response or "Oracle task completed successfully.",
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

        # 1. Query status
        status_call_id = context.id_factory.next(record_type="tool_call", sequence=tool_calls_made)
        status_call = ToolCall(
            call_id=status_call_id,
            run_id=context.run_id,
            tool_name="flight.get_status",
            arguments={"flight_number": flight_number},
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
                arguments={"flight_number": flight_number},
                mutation_class="read_only",
                start_time=context.clock.now(),
            )
            res = await executor.execute(tool_call=status_call_2, context=context)
            tool_calls_made += 1

        status_str = "unknown"
        origin = "JFK"
        destination = "LHR"
        date = "2026-08-01"

        if res.status == "success" and isinstance(res.result, dict):
            status_str = str(res.result.get("status", "unknown")).lower()
            origin = res.result.get("origin", origin)
            destination = res.result.get("destination", destination)
            date = res.result.get("scheduled_departure", date)[:10]

        # 2. If delayed or cancelled, search alternatives
        alternatives: list[Any] = []
        if status_str in ("delayed", "cancelled"):
            search_call_id = context.id_factory.next(
                record_type="tool_call", sequence=tool_calls_made
            )
            search_call = ToolCall(
                call_id=search_call_id,
                run_id=context.run_id,
                tool_name="flight.search",
                arguments={
                    "origin": origin,
                    "destination": destination,
                    "date": date,
                },
                mutation_class="read_only",
                start_time=context.clock.now(),
            )
            s_res = await executor.execute(tool_call=search_call, context=context)
            tool_calls_made += 1
            if s_res.status == "success" and isinstance(s_res.result, dict):
                alternatives = s_res.result.get("flights", [])

        # Formulate simple response
        alt_summary = f" Found {len(alternatives)} alternative flight(s)." if alternatives else ""
        final_text = f"Flight {flight_number} status is {status_str}.{alt_summary}"

        return AgentRunResult(
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

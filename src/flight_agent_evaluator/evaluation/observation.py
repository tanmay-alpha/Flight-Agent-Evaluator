"""Observation model extracting trusted trajectory records from runtime journals.

Converts journal tool execution events and domain records into an immutable,
canonical ObservedTrajectory data structure used for graph matching.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from flight_agent_evaluator.recording.journal import HashChainJournal


class ObservedToolAction(BaseModel):
    """A single tool action observed in the execution journal."""

    call_id: str = Field(..., description="Unique tool call identifier.")
    sequence_number: int = Field(..., description="1-indexed sequence order in journal.")
    tool_name: str = Field(..., description="Name of invoked tool.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Canonical tool arguments.")
    mutation_class: str = Field(default="read_only", description="Authoritative mutation class.")
    start_time: str = Field(..., description="ISO-8601 start timestamp.")
    end_time: str | None = Field(default=None, description="ISO-8601 end timestamp.")
    status: str = Field(
        default="success", description="Execution outcome ('success', 'failure', 'timeout', etc.)."
    )
    result: dict[str, Any] | None = Field(default=None, description="Returned result dictionary.")
    error: dict[str, Any] | None = Field(default=None, description="Returned error dictionary.")
    is_retry: bool = Field(default=False, description="True if action is a retry of a failed call.")
    retry_count: int = Field(default=0, description="Retry attempt index.")

    @property
    def is_successful(self) -> bool:
        """True if the tool call completed successfully without error."""
        return self.status == "success" and self.error is None


class ObservedTrajectory(BaseModel):
    """Canonical representation of an observed agent run extracted from journal logs."""

    scenario_id: str = Field(..., description="Scenario identifier.")
    run_id: str = Field(..., description="Run identifier.")
    actions: list[ObservedToolAction] = Field(
        default_factory=list, description="Ordered tool actions."
    )
    domain_events: list[dict[str, Any]] = Field(
        default_factory=list, description="Recorded domain events."
    )
    final_response: str | None = Field(default=None, description="Final response emitted by agent.")

    @property
    def total_calls(self) -> int:
        return len(self.actions)


def extract_observed_trajectory(
    scenario_id: str,
    run_id: str,
    journal: HashChainJournal,
    final_response: str | None = None,
) -> ObservedTrajectory:
    """Extract an ObservedTrajectory from a HashChainJournal instance."""
    records = journal.entries
    actions_map: dict[str, ObservedToolAction] = {}
    ordered_actions: list[ObservedToolAction] = []
    domain_events: list[dict[str, Any]] = []

    seq = 1
    seen_calls: dict[str, int] = {}

    for rec in records:
        event_type = rec.type
        payload = rec.payload

        if event_type == "tool_call":
            call_id = str(payload.get("call_id", ""))
            tool_name = str(payload.get("tool_name", ""))
            args = payload.get("arguments", {})
            mut_class = str(payload.get("mutation_class", "read_only"))
            start_time = str(payload.get("start_time", ""))

            retry_cnt = seen_calls.get(tool_name, 0)
            is_retry = retry_cnt > 0
            seen_calls[tool_name] = retry_cnt + 1

            act = ObservedToolAction(
                call_id=call_id,
                sequence_number=seq,
                tool_name=tool_name,
                arguments=args if isinstance(args, dict) else {},
                mutation_class=mut_class,
                start_time=start_time,
                is_retry=is_retry,
                retry_count=retry_cnt,
            )
            actions_map[call_id] = act
            ordered_actions.append(act)
            seq += 1

        elif event_type == "tool_result":
            call_id = str(payload.get("call_id", ""))
            if call_id in actions_map:
                act = actions_map[call_id]
                act.end_time = str(payload.get("end_time", ""))
                res = payload.get("result")
                err = payload.get("error")
                status = payload.get("status")
                if status is not None:
                    act.status = str(status)
                elif err is not None:
                    act.status = "failure"
                else:
                    act.status = "success"

                if isinstance(res, dict):
                    act.result = res
                elif res is not None:
                    act.result = {"value": res}
                if isinstance(err, dict):
                    act.error = err
                elif err is not None:
                    act.error = {"message": str(err)}

        elif event_type == "domain_event":
            domain_events.append(payload)

    return ObservedTrajectory(
        scenario_id=scenario_id,
        run_id=run_id,
        actions=ordered_actions,
        domain_events=domain_events,
        final_response=final_response,
    )

"""Observation model extracting trusted trajectory records from runtime journals.

Converts journal tool execution events and domain records into an immutable,
canonical ObservedTrajectory data structure used for graph matching.
"""

from __future__ import annotations

from datetime import datetime
from functools import cache
from typing import Any

from pydantic import BaseModel, Field

from flight_agent_evaluator.canonical import canonical_json
from flight_agent_evaluator.recording.journal import HashChainJournal

NO_RESULT_STATUS = "no_result"
"""Status of a journaled tool call for which no ``tool_result`` was recorded."""

UNKNOWN_MUTATION_CLASS = "unknown"
"""Mutation class of a tool that is neither registered, packaged, nor self-declared."""


@cache
def _tool_catalog() -> dict[str, str]:
    """Registry-derived mutation class of every packaged tool, in any scenario mode."""
    from flight_agent_evaluator.tools.base import build_transactional_registry

    registry = build_transactional_registry()
    return {name: h.tool_definition.mutation_class for name, h in registry.handlers.items()}


def catalog_mutation_class(tool_name: str) -> str | None:
    """Return the authoritative mutation class of a packaged tool, or None if unknown."""
    return _tool_catalog().get(tool_name)


class ObservedToolAction(BaseModel):
    """A single tool action observed in the execution journal."""

    call_id: str = Field(..., description="Unique tool call identifier.")
    sequence_number: int = Field(..., description="1-indexed order among observed tool calls.")
    journal_sequence: int | None = Field(
        default=None, description="Journal seq of the tool_call entry (trusted evidence ref)."
    )
    result_journal_sequence: int | None = Field(
        default=None, description="Journal seq of the matching tool_result entry."
    )
    tool_name: str = Field(..., description="Name of invoked tool.")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Canonical tool arguments.")
    mutation_class: str = Field(default="read_only", description="Authoritative mutation class.")
    authorization_decision: str | None = Field(
        default=None, description="Executor authorization decision ('allowed'/'denied')."
    )
    called_at: datetime | None = Field(default=None, description="Journal time of the call.")
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

    @property
    def error_type(self) -> str | None:
        """Typed error category recorded by the executor, if the call failed."""
        if self.error is None:
            return None
        value = self.error.get("error_type")
        return str(value) if value is not None else None

    @property
    def is_mutating(self) -> bool:
        """True when the mutation class is known and not read-only.

        A tool that is neither registered nor packaged and declared no class
        (``"unknown"``) is not treated as a mutation attempt.
        """
        return self.mutation_class not in ("read_only", UNKNOWN_MUTATION_CLASS)


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
    final_response_sequence: int | None = Field(
        default=None, description="Journal seq of the final_response entry, if journaled."
    )

    @property
    def total_calls(self) -> int:
        return len(self.actions)


def redundant_call_ids(trajectory: ObservedTrajectory) -> set[str]:
    """Identical calls after success without an intervening state-changing call.

    Failed attempts do not make retries redundant. Every mutating attempt
    invalidates cached reads, including ambiguous outcomes whose state is unknown.
    """
    seen: set[tuple[str, str]] = set()
    redundant: set[str] = set()
    for action in trajectory.actions:
        key = (action.tool_name, canonical_json(action.arguments))
        if key in seen:
            redundant.add(action.call_id)
        if action.is_mutating:
            seen.clear()
        if action.is_successful:
            seen.add(key)
    return redundant


def _resolve_mutation_class(payload: dict[str, Any], tool_name: str) -> str:
    recorded = payload.get("mutation_class")
    if isinstance(recorded, str) and recorded:
        return recorded
    # Unregistered in this scenario mode (e.g. a booking tool requested in a read-only
    # run): fall back to the packaged catalog, then to the caller's declared class.
    known = catalog_mutation_class(tool_name)
    if known is not None:
        return known
    requested = payload.get("requested_mutation_class")
    if isinstance(requested, str) and requested:
        return requested
    return UNKNOWN_MUTATION_CLASS


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
    final_response_sequence: int | None = None
    journaled_response: str | None = None

    seq = 1
    seen_calls: dict[str, int] = {}

    for rec in records:
        event_type = rec.type
        payload = rec.payload

        if event_type == "tool_call":
            call_id = str(payload.get("call_id", ""))
            tool_name = str(payload.get("tool_name", ""))
            args = payload.get("arguments", {})
            decision = payload.get("authorization_decision")

            retry_cnt = seen_calls.get(tool_name, 0)
            seen_calls[tool_name] = retry_cnt + 1

            act = ObservedToolAction(
                call_id=call_id,
                sequence_number=seq,
                journal_sequence=rec.seq,
                tool_name=tool_name,
                arguments=args if isinstance(args, dict) else {},
                mutation_class=_resolve_mutation_class(payload, tool_name),
                authorization_decision=str(decision) if decision is not None else None,
                called_at=rec.time,
                start_time=str(payload.get("start_time", "")),
                status=NO_RESULT_STATUS,
                is_retry=retry_cnt > 0,
                retry_count=retry_cnt,
            )
            actions_map[call_id] = act
            ordered_actions.append(act)
            seq += 1

        elif event_type == "tool_result":
            call_id = str(payload.get("call_id", ""))
            if call_id in actions_map:
                act = actions_map[call_id]
                act.result_journal_sequence = rec.seq
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

        elif event_type == "final_response":
            final_response_sequence = rec.seq
            response = payload.get("response")
            journaled_response = str(response) if response is not None else None

    return ObservedTrajectory(
        scenario_id=scenario_id,
        run_id=run_id,
        actions=ordered_actions,
        domain_events=domain_events,
        final_response=final_response if final_response is not None else journaled_response,
        final_response_sequence=final_response_sequence,
    )

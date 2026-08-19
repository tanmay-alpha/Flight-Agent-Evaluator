"""Semantic comparator for original and replayed execution traces.

Compares ordered SemanticJournalEvent sequences to detect any behavioral, argument,
payload, status, error, fault, state, or final response divergence.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.recording.contracts import DivergenceRecord
from flight_agent_evaluator.replay.projection import (
    SemanticEventType,
    SemanticJournalEvent,
    compute_semantic_recording_digest,
)


class SemanticDivergenceType(StrEnum):
    """Specific categories of semantic replay divergences."""

    MISSING_EVENT = "missing_event"
    EXTRA_EVENT = "extra_event"
    EVENT_TYPE_MISMATCH = "event_type_mismatch"
    TOOL_NAME_MISMATCH = "tool_name_mismatch"
    TOOL_ARGUMENT_MISMATCH = "tool_argument_mismatch"
    TOOL_RESULT_STATUS_MISMATCH = "tool_result_status_mismatch"
    TOOL_RESULT_VALUE_MISMATCH = "tool_result_value_mismatch"
    TOOL_ERROR_MISMATCH = "tool_error_mismatch"
    FAULT_MISMATCH = "fault_mismatch"
    DOMAIN_EVENT_MISMATCH = "domain_event_mismatch"
    STATE_MISMATCH = "state_mismatch"
    FINAL_RESPONSE_MISMATCH = "final_response_mismatch"
    LOGICAL_TIME_MISMATCH = "logical_time_mismatch"
    STOP_REASON_MISMATCH = "stop_reason_mismatch"
    PROVENANCE_MISMATCH = "provenance_mismatch"
    RECORDING_TAMPERED = "recording_tampered"
    UNSUPPORTED_SEMANTIC_EVENT = "unsupported_semantic_event"


class SemanticDivergenceRecord(ContractModel):
    """Detailed record of one detected semantic divergence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    kind: SemanticDivergenceType
    detail: str
    field_pointer: str | None = None
    expected_value: str | None = None
    observed_value: str | None = None

    def to_legacy_divergence(self) -> DivergenceRecord:
        """Convert to legacy DivergenceRecord for backward compatibility."""
        return DivergenceRecord(
            sequence=self.sequence,
            kind=self.kind.value,
            detail=self.detail,
            field_pointer=self.field_pointer,
            expected_value=self.expected_value,
            observed_value=self.observed_value,
        )


class SemanticReplayComparison(ContractModel):
    """Result of comparing original vs replay semantic traces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verified: bool
    divergences: tuple[SemanticDivergenceRecord, ...] = Field(default_factory=tuple)
    first_divergence_sequence: int | None = None
    total_divergence_count: int = 0
    returned_divergence_count: int = 0
    original_semantic_digest: str = ""
    replay_semantic_digest: str = ""


class SemanticReplayComparator:
    """Ordered event-by-event comparator for semantic replay verification."""

    def __init__(self, max_divergences: int = 20) -> None:
        self._max_divergences = max_divergences

    def compare(
        self,
        original: tuple[SemanticJournalEvent, ...] | list[SemanticJournalEvent],
        replay: tuple[SemanticJournalEvent, ...] | list[SemanticJournalEvent],
    ) -> SemanticReplayComparison:
        """Compare original and replayed semantic event streams."""
        orig_events = tuple(original)
        replay_events = tuple(replay)

        orig_digest = compute_semantic_recording_digest(orig_events)
        replay_digest = compute_semantic_recording_digest(replay_events)

        divergences: list[SemanticDivergenceRecord] = []
        first_div_seq: int | None = None
        total_divergences = 0

        def _add_div(
            seq: int,
            kind: SemanticDivergenceType,
            detail: str,
            pointer: str | None = None,
            expected: Any = None,
            observed: Any = None,
        ) -> None:
            nonlocal first_div_seq, total_divergences
            total_divergences += 1
            if first_div_seq is None:
                first_div_seq = seq
            if len(divergences) < self._max_divergences:
                divergences.append(
                    SemanticDivergenceRecord(
                        sequence=seq,
                        kind=kind,
                        detail=detail,
                        field_pointer=pointer,
                        expected_value=json.dumps(expected, sort_keys=True)
                        if expected is not None
                        else None,
                        observed_value=json.dumps(observed, sort_keys=True)
                        if observed is not None
                        else None,
                    )
                )

        min_len = min(len(orig_events), len(replay_events))

        for idx in range(min_len):
            o_ev = orig_events[idx]
            r_ev = replay_events[idx]
            seq = o_ev.sequence

            if o_ev.event_type != r_ev.event_type:
                _add_div(
                    seq=seq,
                    kind=SemanticDivergenceType.EVENT_TYPE_MISMATCH,
                    detail=f"Event type mismatch: expected {o_ev.event_type.value}, observed {r_ev.event_type.value}",
                    expected=o_ev.event_type.value,
                    observed=r_ev.event_type.value,
                )
                continue

            if o_ev.event_type == SemanticEventType.TOOL_CALL:
                o_name = o_ev.payload.get("tool_name")
                r_name = r_ev.payload.get("tool_name")
                if o_name != r_name:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.TOOL_NAME_MISMATCH,
                        detail=f"Tool name mismatch: expected {o_name!r}, observed {r_name!r}",
                        pointer="/payload/tool_name",
                        expected=o_name,
                        observed=r_name,
                    )

                o_args = o_ev.payload.get("arguments", {})
                r_args = r_ev.payload.get("arguments", {})
                if o_args != r_args:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.TOOL_ARGUMENT_MISMATCH,
                        detail=f"Tool arguments mismatch for {o_name}: {o_args} != {r_args}",
                        pointer="/payload/arguments",
                        expected=o_args,
                        observed=r_args,
                    )

            elif o_ev.event_type == SemanticEventType.TOOL_RESULT:
                o_stat = o_ev.payload.get("status")
                r_stat = r_ev.payload.get("status")
                if o_stat != r_stat:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.TOOL_RESULT_STATUS_MISMATCH,
                        detail=f"Tool result status mismatch: expected {o_stat!r}, observed {r_stat!r}",
                        pointer="/payload/status",
                        expected=o_stat,
                        observed=r_stat,
                    )

                o_val = o_ev.payload.get("value")
                r_val = r_ev.payload.get("value")
                if o_val != r_val:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.TOOL_RESULT_VALUE_MISMATCH,
                        detail=f"Tool result value payload mismatch: {o_val} != {r_val}",
                        pointer="/payload/value",
                        expected=o_val,
                        observed=r_val,
                    )

                o_err = o_ev.payload.get("error")
                r_err = r_ev.payload.get("error")
                if o_err != r_err:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.TOOL_ERROR_MISMATCH,
                        detail=f"Tool error mismatch: {o_err} != {r_err}",
                        pointer="/payload/error",
                        expected=o_err,
                        observed=r_err,
                    )

            elif o_ev.event_type == SemanticEventType.FAULT_INJECTED:
                if o_ev.payload != r_ev.payload:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.FAULT_MISMATCH,
                        detail=f"Fault injection mismatch: {o_ev.payload} != {r_ev.payload}",
                        pointer="/payload",
                        expected=o_ev.payload,
                        observed=r_ev.payload,
                    )

            elif o_ev.event_type == SemanticEventType.DOMAIN_EVENT:
                if o_ev.payload != r_ev.payload:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.DOMAIN_EVENT_MISMATCH,
                        detail=f"Domain event payload mismatch: {o_ev.payload} != {r_ev.payload}",
                        pointer="/payload",
                        expected=o_ev.payload,
                        observed=r_ev.payload,
                    )

            elif o_ev.event_type == SemanticEventType.STATE_SNAPSHOT:
                if o_ev.payload != r_ev.payload:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.STATE_MISMATCH,
                        detail=f"State snapshot mismatch: {o_ev.payload} != {r_ev.payload}",
                        pointer="/payload",
                        expected=o_ev.payload,
                        observed=r_ev.payload,
                    )

            elif o_ev.event_type == SemanticEventType.FINAL_RESPONSE:
                o_resp = o_ev.payload.get("response")
                r_resp = r_ev.payload.get("response")
                if o_resp != r_resp:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.FINAL_RESPONSE_MISMATCH,
                        detail=f"Final response mismatch: {o_resp!r} != {r_resp!r}",
                        pointer="/payload/response",
                        expected=o_resp,
                        observed=r_resp,
                    )

            elif o_ev.event_type == SemanticEventType.RUN_COMPLETED:
                o_stop = o_ev.payload.get("stop_reason")
                r_stop = r_ev.payload.get("stop_reason")
                if o_stop != r_stop:
                    _add_div(
                        seq=seq,
                        kind=SemanticDivergenceType.STOP_REASON_MISMATCH,
                        detail=f"Stop reason mismatch: {o_stop!r} != {r_stop!r}",
                        pointer="/payload/stop_reason",
                        expected=o_stop,
                        observed=r_stop,
                    )

            elif o_ev.payload != r_ev.payload:
                _add_div(
                    seq=seq,
                    kind=SemanticDivergenceType.EVENT_TYPE_MISMATCH,
                    detail=f"Payload divergence on event {o_ev.event_type.value}",
                    pointer="/payload",
                    expected=o_ev.payload,
                    observed=r_ev.payload,
                )

        if len(orig_events) > len(replay_events):
            for missing in orig_events[min_len:]:
                _add_div(
                    seq=missing.sequence,
                    kind=SemanticDivergenceType.MISSING_EVENT,
                    detail=f"Missing event in replay: sequence={missing.sequence}, type={missing.event_type.value}",
                    expected=missing.payload,
                )
        elif len(replay_events) > len(orig_events):
            for extra in replay_events[min_len:]:
                _add_div(
                    seq=extra.sequence,
                    kind=SemanticDivergenceType.EXTRA_EVENT,
                    detail=f"Extra event in replay: sequence={extra.sequence}, type={extra.event_type.value}",
                    observed=extra.payload,
                )

        verified = (total_divergences == 0) and (orig_digest == replay_digest)

        return SemanticReplayComparison(
            verified=verified,
            divergences=tuple(divergences),
            first_divergence_sequence=first_div_seq,
            total_divergence_count=total_divergences,
            returned_divergence_count=len(divergences),
            original_semantic_digest=orig_digest,
            replay_semantic_digest=replay_digest,
        )

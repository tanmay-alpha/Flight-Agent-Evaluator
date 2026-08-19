"""Semantic event projection for run journal entries.

Projects raw journal entries into versioned, canonical SemanticJournalEvent instances.
Operational metadata (such as wall-clock timestamps, OS process IDs, filesystem paths,
and host machine identifiers) are excluded so that semantic digests reflect observable
behaviour deterministically.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.recording.contracts import JournalEntry

SEMANTIC_EVENT_PROJECTION_VERSION: str = "semantic-events-v1"


class SemanticEventType(StrEnum):
    """Normalized semantic event types."""

    RUN_STARTED = "run_started"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FAULT_INJECTED = "fault_injected"
    DOMAIN_EVENT = "domain_event"
    STATE_SNAPSHOT = "state_snapshot"
    CHECKPOINT = "checkpoint"
    FINAL_RESPONSE = "final_response"
    RUN_COMPLETED = "run_completed"
    UNKNOWN = "unknown"


def _canonical_json(data: Any) -> str:
    """Deterministic JSON string with sorted keys and compact separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_sha256(content: str) -> str:
    """Compute SHA-256 hex digest of string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class SemanticJournalEvent(ContractModel):
    """Canonical representation of an observable event in a run execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int
    event_type: SemanticEventType
    payload: dict[str, Any]
    logical_time: str | None = None
    semantic_digest: str = Field(default="")

    def canonical_digest(self) -> str:
        """Compute the deterministic SHA-256 digest of this semantic event."""
        body = {
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "payload": self.payload,
            "logical_time": self.logical_time,
        }
        return _compute_sha256(_canonical_json(body))


def project_semantic_event(entry: JournalEntry) -> SemanticJournalEvent:
    """Project a raw JournalEntry into a versioned SemanticJournalEvent."""
    raw_type = entry.type
    raw_payload = dict(entry.payload) if isinstance(entry.payload, dict) else {}

    # Extract deterministic logical time if present, ignoring wall-clock time
    logical_time = None
    if "logical_time" in raw_payload:
        logical_time = str(raw_payload["logical_time"])
    elif "virtual_time" in raw_payload:
        logical_time = str(raw_payload["virtual_time"])

    # Filter operational noise out of payload
    cleaned_payload: dict[str, Any] = {}

    if raw_type == "run_started":
        ev_type = SemanticEventType.RUN_STARTED
        cleaned_payload = {
            "scenario_id": str(raw_payload.get("scenario_id", "")),
            "seed": raw_payload.get("seed", 0),
        }
        if "scenario_version" in raw_payload:
            cleaned_payload["scenario_version"] = raw_payload["scenario_version"]

    elif raw_type == "tool_call":
        ev_type = SemanticEventType.TOOL_CALL
        cleaned_payload = {
            "tool_name": str(raw_payload.get("tool_name", "")),
            "arguments": raw_payload.get("arguments", {}),
            "call_id": str(raw_payload.get("call_id", "")),
        }
        if "mutation_class" in raw_payload:
            cleaned_payload["mutation_class"] = raw_payload["mutation_class"]

    elif raw_type == "tool_result":
        ev_type = SemanticEventType.TOOL_RESULT
        cleaned_payload = {
            "call_id": str(raw_payload.get("call_id", "")),
            "status": str(raw_payload.get("status", "")),
            "value": raw_payload.get("value"),
            "error": raw_payload.get("error"),
        }
        if "retryable" in raw_payload:
            cleaned_payload["retryable"] = raw_payload["retryable"]

    elif raw_type == "fault_injected":
        ev_type = SemanticEventType.FAULT_INJECTED
        cleaned_payload = {
            "fault_type": str(raw_payload.get("fault_type", "")),
            "target": str(raw_payload.get("target", "")),
            "parameters": raw_payload.get("parameters", {}),
        }

    elif raw_type == "domain_event":
        ev_type = SemanticEventType.DOMAIN_EVENT
        cleaned_payload = {
            "event_type": str(raw_payload.get("event_type", "")),
            "data": raw_payload.get("data", {}),
        }

    elif raw_type == "state_snapshot":
        ev_type = SemanticEventType.STATE_SNAPSHOT
        cleaned_payload = raw_payload

    elif raw_type == "checkpoint":
        ev_type = SemanticEventType.CHECKPOINT
        cleaned_payload = {
            "label": str(raw_payload.get("label", "")),
            "state": raw_payload.get("state", {}),
        }

    elif raw_type == "final_response" or raw_type == "driver_completed":
        ev_type = SemanticEventType.FINAL_RESPONSE
        cleaned_payload = {
            "response": str(raw_payload.get("response", raw_payload.get("final_response", ""))),
        }

    elif raw_type == "run_completed":
        ev_type = SemanticEventType.RUN_COMPLETED
        cleaned_payload = {
            "stop_reason": str(raw_payload.get("stop_reason", "")),
        }

    else:
        ev_type = SemanticEventType.UNKNOWN
        cleaned_payload = raw_payload

    draft = SemanticJournalEvent(
        sequence=entry.seq,
        event_type=ev_type,
        payload=cleaned_payload,
        logical_time=logical_time,
        semantic_digest="",
    )
    digest = draft.canonical_digest()
    return draft.model_copy(update={"semantic_digest": digest})


def compute_semantic_recording_digest(
    events: tuple[SemanticJournalEvent, ...] | list[SemanticJournalEvent],
) -> str:
    """Compute an authoritative SHA-256 digest identifying a semantic sequence."""
    if not events:
        return _compute_sha256("[]")
    digests = [e.semantic_digest for e in events]
    return _compute_sha256(_canonical_json(digests))

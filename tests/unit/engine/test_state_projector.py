"""Comprehensive tests for StateProjector."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flight_agent_evaluator.engine.state import StateProjector
from flight_agent_evaluator.recording.contracts import JournalEntry
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.state import StateSnapshot


def test_state_projector_run_started_and_completed():
    projector = StateProjector()
    state = StateSnapshot()

    s1 = projector.project_entry(
        state, "run_started", {"time": "2026-01-01T00:00:00+00:00", "scenario_id": "sc-1"}
    )
    assert s1.data["_timeline"]["started_at"] == "2026-01-01T00:00:00+00:00"

    s2 = projector.project_entry(s1, "run_completed", {"time": "2026-01-01T00:05:00+00:00"})
    assert s2.data["_timeline"]["completed_at"] == "2026-01-01T00:05:00+00:00"


def test_state_projector_tool_call_and_result():
    projector = StateProjector()
    state = StateSnapshot()

    s1 = projector.project_entry(
        state,
        "tool_call",
        {
            "call_id": "call-1",
            "tool_name": "flight.get_status",
            "arguments": {"flight_number": "AA100"},
            "mutation_class": "read_only",
        },
    )
    assert len(s1.data["tool_calls"]) == 1
    assert s1.data["tool_calls"][0]["status"] == "pending"

    s2 = projector.project_entry(
        s1,
        "tool_result",
        {
            "call_id": "call-1",
            "status": "success",
            "result": {"status": "ON_TIME"},
        },
    )
    assert s2.data["tool_calls"][0]["status"] == "success"
    assert s2.data["tool_calls"][0]["result"] == {"status": "ON_TIME"}


def test_state_projector_tool_result_with_error():
    projector = StateProjector()
    state = StateSnapshot()
    s1 = projector.project_entry(
        state,
        "tool_call",
        {
            "call_id": "call-err",
            "tool_name": "flight.get_status",
            "arguments": {},
        },
    )
    s2 = projector.project_entry(
        s1,
        "tool_result",
        {
            "call_id": "call-err",
            "status": "failure",
            "error": {"error_type": "invalid_arguments", "message": "Missing flight"},
        },
    )
    assert s2.data["tool_calls"][0]["status"] == "failure"
    assert s2.data["tool_calls"][0]["error"]["error_type"] == "invalid_arguments"


def test_state_projector_driver_completed():
    projector = StateProjector()
    state = StateSnapshot()

    s1 = projector.project_entry(
        state,
        "driver_completed",
        {
            "final_response": "Flight is delayed by 2 hours.",
            "checkpoints": ["cp-1", "cp-2"],
        },
    )
    assert s1.data["final_response"] == "Flight is delayed by 2 hours."
    assert s1.data["checkpoints"] == ["cp-1", "cp-2"]


def test_state_projector_domain_events_and_nested_updates():
    projector = StateProjector()
    state = StateSnapshot()

    s1 = projector.project_entry(
        state,
        "domain_event",
        {
            "event_type": "booking_updated",
            "booking_id": "BK123",
            "state": "CONFIRMED",
        },
    )
    assert len(s1.data["events"]) == 1
    assert s1.data["bookings"]["BK123"]["state"] == "CONFIRMED"

    s2 = projector.project_entry(
        s1,
        "domain_event",
        {
            "event_type": "approval_updated",
            "request_id": "REQ456",
            "state": "GRANTED",
        },
    )
    assert len(s2.data["events"]) == 2
    assert s2.data["approvals"]["REQ456"]["state"] == "GRANTED"


def test_state_projector_project_journal():
    projector = StateProjector()
    journal = HashChainJournal()
    run_id = uuid.uuid4()

    journal.append(
        JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=run_id,
            correlation_id="c1",
            time=datetime.now(UTC),
            payload={"scenario_id": "s1"},
            prev_hash="",
            hash="",
        )
    )
    journal.append(
        JournalEntry(
            v=1,
            seq=2,
            id=uuid.uuid4(),
            type="tool_call",
            run_id=run_id,
            correlation_id="c2",
            time=datetime.now(UTC),
            payload={"call_id": "c-1", "tool_name": "flight.get_status", "arguments": {}},
            prev_hash=journal.entries[0].hash,
            hash="",
        )
    )
    journal.append(
        JournalEntry(
            v=1,
            seq=3,
            id=uuid.uuid4(),
            type="tool_result",
            run_id=run_id,
            correlation_id="c3",
            time=datetime.now(UTC),
            payload={"call_id": "c-1", "status": "success", "result": {"flight": "AA100"}},
            prev_hash=journal.entries[1].hash,
            hash="",
        )
    )

    final_state = projector.project_journal(journal)
    assert len(final_state.data["tool_calls"]) == 1
    assert final_state.data["tool_calls"][0]["result"] == {"flight": "AA100"}

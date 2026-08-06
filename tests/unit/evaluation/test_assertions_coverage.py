"""Additional branch coverage tests for AssertionEvaluator."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flight_agent_evaluator.contracts.evaluation import (
    ApprovalStateAssertion,
    BookingStateAssertion,
    EventCountAssertion,
    MaximumLatencyAssertion,
    ReplayDeterminismAssertion,
    ToolCallCountAssertion,
)
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.recording.contracts import DivergenceRecord, JournalEntry, ReplayReport
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.state import StateSnapshot


def test_eval_tool_call_count_branches():
    evaluator = AssertionEvaluator()
    journal = HashChainJournal()
    entry = JournalEntry(
        v=1,
        seq=1,
        id=uuid.uuid4(),
        type="tool_call",
        run_id=uuid.uuid4(),
        correlation_id="c1",
        time=datetime.now(UTC),
        payload={"tool_name": "search"},
        prev_hash="",
        hash="",
    )
    journal.append_raw(entry)

    # Missing tool_name (instantiated directly)
    a_missing = ToolCallCountAssertion.model_construct(assertion_id="a1", tool_name="", min_count=2)
    o_missing = evaluator._eval_tool_assertion(a_missing, journal)
    assert o_missing.status == "skipped"

    # Count below min_count
    a_min = ToolCallCountAssertion(assertion_id="a2", tool_name="search", min_count=2)
    o_min = evaluator._eval_tool_assertion(a_min, journal)
    assert o_min.status == "failed"

    # Count above max_count
    a_max = ToolCallCountAssertion(assertion_id="a3", tool_name="search", max_count=0)
    o_max = evaluator._eval_tool_assertion(a_max, journal)
    assert o_max.status == "failed"


def test_eval_event_count_branches():
    evaluator = AssertionEvaluator()
    journal = HashChainJournal()
    run_id = uuid.uuid4()
    for i in range(3):
        journal.append_raw(
            JournalEntry(
                v=1,
                seq=i + 1,
                id=uuid.uuid4(),
                type="domain_event",
                run_id=run_id,
                correlation_id=f"c{i}",
                time=datetime.now(UTC),
                payload={"event_type": "flight_delayed"},
                prev_hash="",
                hash="",
            )
        )

    # Min count failed
    a_min = EventCountAssertion(assertion_id="e1", event_type="flight_delayed", min_count=5)
    o_min = evaluator._eval_one(a_min, StateSnapshot(), journal, None)
    assert o_min.status == "failed"

    # Max count failed
    a_max = EventCountAssertion(assertion_id="e2", event_type="flight_delayed", max_count=1)
    o_max = evaluator._eval_one(a_max, StateSnapshot(), journal, None)
    assert o_max.status == "failed"


def test_eval_booking_and_approval_state_branches():
    evaluator = AssertionEvaluator()

    # Booking missing in state
    a_b1 = BookingStateAssertion(assertion_id="b1", booking_id="B1", expected_state="CONFIRMED")
    o_b1 = evaluator._eval_one(a_b1, StateSnapshot(), None, None)
    assert o_b1.status == "inconclusive"

    # Booking state match vs mismatch
    state_b = StateSnapshot(data={"bookings": {"B1": {"state": "CANCELLED"}}})
    o_b2 = evaluator._eval_one(a_b1, state_b, None, None)
    assert o_b2.status == "failed"

    a_b3 = BookingStateAssertion(assertion_id="b3", booking_id="B1", expected_state="CANCELLED")
    o_b3 = evaluator._eval_one(a_b3, state_b, None, None)
    assert o_b3.status == "passed"

    # Approval missing in state
    a_ap1 = ApprovalStateAssertion(assertion_id="ap1", request_id="R1", expected_state="granted")
    o_ap1 = evaluator._eval_one(a_ap1, StateSnapshot(), None, None)
    assert o_ap1.status == "inconclusive"

    # Approval state match vs mismatch
    state_ap = StateSnapshot(data={"approvals": {"R1": {"state": "denied"}}})
    o_ap2 = evaluator._eval_one(a_ap1, state_ap, None, None)
    assert o_ap2.status == "failed"

    a_ap3 = ApprovalStateAssertion(assertion_id="ap3", request_id="R1", expected_state="denied")
    o_ap3 = evaluator._eval_one(a_ap3, state_ap, None, None)
    assert o_ap3.status == "passed"


def test_eval_latency_and_replay_determinism_branches():
    evaluator = AssertionEvaluator()

    # Latency pass vs fail
    state = StateSnapshot(
        data={
            "_timeline": {
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:00:10Z",
            }
        }
    )
    a_lat = MaximumLatencyAssertion(assertion_id="lat1", max_seconds=5)
    o_lat_fail = evaluator._eval_one(a_lat, state, None, None)
    assert o_lat_fail.status == "failed"

    a_lat_pass = MaximumLatencyAssertion(assertion_id="lat2", max_seconds=15)
    o_lat_pass = evaluator._eval_one(a_lat_pass, state, None, None)
    assert o_lat_pass.status == "passed"

    # Replay determinism without report vs pass vs fail report
    a_rep = ReplayDeterminismAssertion(assertion_id="rep1")
    o_rep_none = evaluator._eval_one(a_rep, StateSnapshot(), None, None)
    assert o_rep_none.status == "inconclusive"

    rep_pass = ReplayReport(
        recording_run_id="r1",
        mode="verification",
        status="behaviour_verified",
        final_digest="0" * 64,
    )
    o_rep_pass = evaluator._eval_one(a_rep, StateSnapshot(), None, rep_pass)
    assert o_rep_pass.status == "passed"

    rep_fail = ReplayReport(
        recording_run_id="r1",
        mode="verification",
        status="behaviour_diverged",
        divergences=(DivergenceRecord(sequence=1, kind="missing_tool", detail="d1"),),
        final_digest="0" * 64,
    )
    o_rep_fail = evaluator._eval_one(a_rep, StateSnapshot(), None, rep_fail)
    assert o_rep_fail.status == "failed"

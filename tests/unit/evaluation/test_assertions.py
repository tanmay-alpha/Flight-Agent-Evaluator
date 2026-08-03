"""Tests for the AssertionEvaluator."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flight_agent_evaluator.contracts.evaluation import (
    ApprovalStateAssertion,
    BookingStateAssertion,
    EventCountAssertion,
    ForbiddenMutationAssertion,
    MaximumLatencyAssertion,
    NoDuplicateSideEffectAssertion,
    ReplayDeterminismAssertion,
    ToolCallCountAssertion,
    ToolCalledAssertion,
    ToolNotCalledAssertion,
)
from flight_agent_evaluator.contracts.scenarios import (
    BenchmarkScenario,
    ScenarioIdentifier,
    ScenarioLimits,
    ScenarioMetadata,
    ScenarioStep,
)
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.recording.contracts import JournalEntry
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.state import StateSnapshot


def _make_scenario(assertions):
    from flight_agent_evaluator.recording.contracts import (
        ProduceFinalResponseStep,
        ScriptedTrajectory,
    )

    return BenchmarkScenario(
        schema_version={"major": 1, "minor": 0, "patch": 0},
        scenario_id=ScenarioIdentifier(id="test-scenario"),
        metadata=ScenarioMetadata(
            title="Test",
            description="Test",
            objective="Test",
        ),
        limits=ScenarioLimits(tool_call_limit=10, time_limit_seconds=60),
        steps=(ScenarioStep(step_id="step-1", description="Step 1"),),
        assertions=tuple(assertions),
        trajectory=ScriptedTrajectory(
            trajectory_id="test-trajectory",
            description="test trajectory",
            steps=(ProduceFinalResponseStep(step_id="step-final", response="done"),),
        ),
    )


def test_evaluate_empty_assertions():
    evaluator = AssertionEvaluator()
    scenario = _make_scenario([])
    state = StateSnapshot()
    result = evaluator.evaluate(
        scenario=scenario,
        state=state,
        journal=None,
        replay_report=None,
        run_id="r",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    assert result.status == "failed"
    assert result.summary.total == 0


def test_evaluate_skipped_assertions():
    evaluator = AssertionEvaluator()
    assertion = ToolCalledAssertion(assertion_id="a1", tool_name="foo")
    scenario = _make_scenario([assertion])
    state = StateSnapshot()
    result = evaluator.evaluate(
        scenario=scenario,
        state=state,
        journal=None,
        replay_report=None,
        run_id="r",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    assert result.status == "failed"
    assert result.summary.skipped == 1


# ---------------------------------------------------------------------------
# Tool call assertions
# ---------------------------------------------------------------------------


def _make_journal_with_tool_calls(run_id: str, tool_names: list[str]) -> HashChainJournal:
    journal = HashChainJournal()
    for i, name in enumerate(tool_names):
        entry = JournalEntry(
            v=1,
            seq=i + 1,
            id=uuid.uuid4(),
            type="tool_call",
            run_id=uuid.UUID(run_id),
            correlation_id=str(uuid.uuid4()),
            time=datetime.now(UTC).isoformat(),
            payload={
                "call_id": str(uuid.uuid4()),
                "tool_name": name,
                "arguments": {},
                "mutation_class": "read" if ("get_status" in name or "search" in name) else "write",
                "idempotency_key": f"key-{i}",
                "result": {"status": "ok"},
            },
            prev_hash="" if i == 0 else "0" * 64,
            hash="0" * 64,
        )
        journal.append_raw(entry)
    return journal


class TestToolCalledAssertions:
    def test_passes_when_tool_was_called(self):
        evaluator = AssertionEvaluator()
        assertion = ToolCalledAssertion(assertion_id="a1", tool_name="flight.get_status")
        journal = _make_journal_with_tool_calls(str(uuid.uuid4()), ["flight.get_status"])
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "passed"

    def test_fails_when_tool_not_called(self):
        evaluator = AssertionEvaluator()
        assertion = ToolCalledAssertion(assertion_id="a2", tool_name="flight.unknown")
        journal = _make_journal_with_tool_calls(str(uuid.uuid4()), ["other"])
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "failed"


class TestToolNotCalledAssertions:
    def test_passes_when_tool_not_called(self):
        evaluator = AssertionEvaluator()
        assertion = ToolNotCalledAssertion(assertion_id="a1", tool_name="flight.cancel")
        journal = _make_journal_with_tool_calls(str(uuid.uuid4()), ["flight.get_status"])
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "passed"

    def test_fails_when_tool_was_called(self):
        evaluator = AssertionEvaluator()
        assertion = ToolNotCalledAssertion(assertion_id="a2", tool_name="flight.cancel")
        journal = _make_journal_with_tool_calls(str(uuid.uuid4()), ["flight.cancel"])
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "failed"


class TestToolCallCountAssertions:
    def test_count_within_range(self):
        evaluator = AssertionEvaluator()
        assertion = ToolCallCountAssertion(
            assertion_id="a1",
            tool_name="search",
            min_count=1,
            max_count=5,
        )
        journal = _make_journal_with_tool_calls(str(uuid.uuid4()), ["search", "search"])
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "passed"

    def test_count_below_min(self):
        evaluator = AssertionEvaluator()
        assertion = ToolCallCountAssertion(
            assertion_id="a2",
            tool_name="search",
            min_count=3,
            max_count=10,
        )
        journal = _make_journal_with_tool_calls(str(uuid.uuid4()), ["search"])
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "failed"

    def test_count_above_max(self):
        evaluator = AssertionEvaluator()
        assertion = ToolCallCountAssertion(
            assertion_id="a3",
            tool_name="search",
            min_count=0,
            max_count=2,
        )
        journal = _make_journal_with_tool_calls(
            str(uuid.uuid4()),
            ["search", "search", "search"],
        )
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "failed"


class TestNoDuplicateSideEffectAssertion:
    def test_passes_no_duplicates(self):
        evaluator = AssertionEvaluator()
        assertion = NoDuplicateSideEffectAssertion(
            assertion_id="a1",
            tool_name="book",
        )
        journal = _make_journal_with_tool_calls(
            str(uuid.uuid4()),
            ["book", "book"],
        )
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "passed"

    def test_fails_on_duplicate_key(self):
        evaluator = AssertionEvaluator()
        assertion = NoDuplicateSideEffectAssertion(
            assertion_id="a2",
            tool_name="book",
        )
        journal = HashChainJournal()
        for i in range(2):
            entry = JournalEntry(
                v=1,
                seq=i + 1,
                id=uuid.uuid4(),
                type="tool_call",
                run_id=uuid.UUID(str(uuid.uuid4())),
                correlation_id=str(uuid.uuid4()),
                time=datetime.now(UTC).isoformat(),
                payload={
                    "tool_name": "book",
                    "idempotency_key": "same-key",
                    "mutation_class": "book",
                },
                prev_hash="" if i == 0 else "0" * 64,
                hash="0" * 64,
            )
            journal.append_raw(entry)
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "failed"


class TestForbiddenMutationAssertion:
    def test_passes_when_read_only(self):
        evaluator = AssertionEvaluator()
        assertion = ForbiddenMutationAssertion(
            assertion_id="a1",
            tool_name="search",
        )
        journal = _make_journal_with_tool_calls(
            str(uuid.uuid4()),
            ["flight.get_status", "flight.search_flights"],
        )
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "passed"

    def test_fails_when_mutation_detected(self):
        evaluator = AssertionEvaluator()
        assertion = ForbiddenMutationAssertion(
            assertion_id="a2",
            tool_name="book",
        )
        journal = _make_journal_with_tool_calls(
            str(uuid.uuid4()),
            ["book"],
        )
        outcome = evaluator._eval_tool_assertion(assertion, journal)
        assert outcome.status == "failed"


class TestEventCountAssertion:
    def test_count_within_range(self):
        evaluator = AssertionEvaluator()
        assertion = EventCountAssertion(
            assertion_id="a1", event_type="domain_event", min_count=1, max_count=5
        )
        journal = HashChainJournal()
        for i in range(3):
            entry = JournalEntry(
                v=1,
                seq=i + 1,
                id=uuid.uuid4(),
                type="domain_event",
                run_id=uuid.UUID(str(uuid.uuid4())),
                correlation_id=str(uuid.uuid4()),
                time=datetime.now(UTC).isoformat(),
                payload={"event_type": "domain_event", "data": {}},
                prev_hash="" if i == 0 else "0" * 64,
                hash="0" * 64,
            )
            journal.append_raw(entry)
        outcome = evaluator._eval_one(assertion, StateSnapshot(), journal, None)
        assert outcome.status == "passed"

    def test_count_below_min(self):
        evaluator = AssertionEvaluator()
        assertion = EventCountAssertion(
            assertion_id="a2", event_type="domain_event", min_count=5, max_count=10
        )
        journal = HashChainJournal()
        outcome = evaluator._eval_one(assertion, StateSnapshot(), journal, None)
        assert outcome.status == "failed"


class TestBookingStateAssertion:
    def test_booking_found_matches(self):
        evaluator = AssertionEvaluator()
        assertion = BookingStateAssertion(
            assertion_id="a1",
            booking_id="BK1",
            expected_state="confirmed",
        )
        state = StateSnapshot(data={"bookings": {"BK1": {"state": "confirmed"}}})
        outcome = evaluator._eval_one(assertion, state, None, None)
        assert outcome.status == "passed"

    def test_booking_found_mismatch(self):
        evaluator = AssertionEvaluator()
        assertion = BookingStateAssertion(
            assertion_id="a2",
            booking_id="BK1",
            expected_state="confirmed",
        )
        state = StateSnapshot(data={"bookings": {"BK1": {"state": "cancelled"}}})
        outcome = evaluator._eval_one(assertion, state, None, None)
        assert outcome.status == "failed"

    def test_booking_missing_inconclusive(self):
        evaluator = AssertionEvaluator()
        assertion = BookingStateAssertion(
            assertion_id="a3",
            booking_id="BK1",
            expected_state="confirmed",
        )
        state = StateSnapshot(data={"bookings": {}})
        outcome = evaluator._eval_one(assertion, state, None, None)
        assert outcome.status == "inconclusive"


class TestApprovalStateAssertion:
    def test_approval_found_matches(self):
        evaluator = AssertionEvaluator()
        assertion = ApprovalStateAssertion(
            assertion_id="a1",
            request_id="APR1",
            expected_state="granted",
        )
        state = StateSnapshot(data={"approvals": {"APR1": {"state": "granted"}}})
        outcome = evaluator._eval_one(assertion, state, None, None)
        assert outcome.status == "passed"

    def test_approval_missing_inconclusive(self):
        evaluator = AssertionEvaluator()
        assertion = ApprovalStateAssertion(
            assertion_id="a2",
            request_id="APR1",
            expected_state="granted",
        )
        state = StateSnapshot(data={"approvals": {}})
        outcome = evaluator._eval_one(assertion, state, None, None)
        assert outcome.status == "inconclusive"


class TestReplayDeterminismAssertion:
    def test_passes_when_verified(self):
        evaluator = AssertionEvaluator()
        assertion = ReplayDeterminismAssertion(assertion_id="a1")
        report = type("R", (), {"status": "verified"})()
        outcome = evaluator._eval_one(assertion, StateSnapshot(), None, report)
        assert outcome.status == "passed"

    def test_fails_when_diverged(self):
        evaluator = AssertionEvaluator()
        assertion = ReplayDeterminismAssertion(assertion_id="a2")
        report = type("R", (), {"status": "diverged"})()
        outcome = evaluator._eval_one(assertion, StateSnapshot(), None, report)
        assert outcome.status == "failed"

    def test_inconclusive_when_no_report(self):
        evaluator = AssertionEvaluator()
        assertion = ReplayDeterminismAssertion(assertion_id="a3")
        outcome = evaluator._eval_one(assertion, StateSnapshot(), None, None)
        assert outcome.status == "inconclusive"


class TestMaximumLatencyAssertion:
    def test_latency_within_limit(self):
        evaluator = AssertionEvaluator()
        assertion = MaximumLatencyAssertion(assertion_id="a1", max_seconds=30)
        state = StateSnapshot(
            data={
                "_timeline": {
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "completed_at": "2024-01-01T00:00:05+00:00",
                }
            }
        )
        outcome = evaluator._eval_one(assertion, state, None, None)
        assert outcome.status == "passed"

    def test_latency_exceeds_limit(self):
        evaluator = AssertionEvaluator()
        assertion = MaximumLatencyAssertion(assertion_id="a2", max_seconds=5)
        state = StateSnapshot(
            data={
                "_timeline": {
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "completed_at": "2024-01-01T00:00:30+00:00",
                }
            }
        )
        outcome = evaluator._eval_one(assertion, state, None, None)
        assert outcome.status == "failed"

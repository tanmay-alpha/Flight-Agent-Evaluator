"""Assertion evaluator for the Phase 2 runtime.

Evaluates assertions against the journal, state, and replay report.
Each assertion type is evaluated objectively against concrete data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flight_agent_evaluator.contracts.evaluation import (
    Assertion,
    AssertionOutcome,
    EvaluationMetric,
    EvaluationResult,
    EvaluationStatus,
    EvaluationSummary,
)
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.state import StateSnapshot


class AssertionEvaluator:
    """Evaluate assertions for a completed run against journal + state."""

    def evaluate(
        self,
        scenario: BenchmarkScenario,
        state: StateSnapshot,
        journal: HashChainJournal | None,
        replay_report: Any | None,
        run_id: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> EvaluationResult:
        """Evaluate all assertions against run data.

        Parameters
        ----------
        scenario: benchmark scenario (provides assertions)
        state: final state snapshot
        journal: trusted journal entries (may be None for replay only)
        replay_report: replay verification report (may be None)
        run_id: run identifier
        started_at: run start timestamp
        ended_at: run end timestamp
        """
        outcomes: list[AssertionOutcome] = []
        passed = 0
        failed = 0
        skipped = 0

        for assertion in scenario.assertions:
            outcome = self._eval_one(assertion, state, journal, replay_report)
            outcomes.append(outcome)
            if outcome.status == "passed":
                passed += 1
            elif outcome.status == "failed":
                failed += 1
            else:
                skipped += 1

        duration_ms = round((ended_at - started_at).total_seconds() * 1000)
        metrics = [EvaluationMetric(name="duration_ms", value=duration_ms)]

        status: EvaluationStatus = "passed" if failed == 0 and passed > 0 else "failed"
        return EvaluationResult(
            evaluation_id=f"eval-{run_id}",
            scenario_id=scenario.scenario_id.id,
            run_id=run_id,
            started_at=started_at,
            ended_at=ended_at,
            status=status,
            summary=EvaluationSummary(
                total=len(outcomes),
                passed=passed,
                failed=failed,
                skipped=skipped,
            ),
            outcomes=tuple(outcomes),
            metrics=tuple(metrics),
        )

    def _eval_one(
        self,
        assertion: Assertion,
        state: StateSnapshot,
        journal: HashChainJournal | None,
        replay_report: Any | None,
    ) -> AssertionOutcome:
        """Evaluate one assertion."""
        atype = assertion.assertion_type

        # Tool call assertions require the journal
        if atype in (
            "tool_called",
            "tool_not_called",
            "tool_call_count",
            "no_duplicate_side_effect",
            "forbidden_mutation",
        ):
            if journal is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Journal is required for tool assertions",
                )
            tool_calls = self._collect_tool_calls(journal)
            return self._eval_tool_assertion(assertion, tool_calls)

        # Event count assertions require the journal
        if atype == "event_count":
            if journal is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Journal is required for event assertions",
                )
            events = self._collect_events(journal, getattr(assertion, "event_type", None))
            min_count = getattr(assertion, "min_count", None)
            max_count = getattr(assertion, "max_count", None)
            if min_count is not None and len(events) < min_count:
                return AssertionOutcome(
                    assertion=assertion,
                    status="failed",
                    message=f"Event count {len(events)} < min {min_count}",
                    observed={"count": len(events)},
                )
            if max_count is not None and len(events) > max_count:
                return AssertionOutcome(
                    assertion=assertion,
                    status="failed",
                    message=f"Event count {len(events)} > max {max_count}",
                    observed={"count": len(events)},
                )
            return AssertionOutcome(
                assertion=assertion,
                status="passed",
                message=f"Event count {len(events)} in range",
                observed={"count": len(events)},
            )

        # Booking state assertion
        if atype == "booking_state":
            booking_id = getattr(assertion, "booking_id", None)
            expected = getattr(assertion, "expected_state", None)
            if not booking_id:
                return AssertionOutcome(
                    assertion=assertion, status="skipped", message="Missing booking_id"
                )
            booking = self._get_state_path(state.data, f"bookings.{booking_id}.state")
            if booking is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="inconclusive",
                    message="Booking not found in state",
                    observed={"booking_id": booking_id},
                )
            if expected is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="inconclusive",
                    message="Missing expected_state",
                    observed={"booking_id": booking_id, "state": booking},
                )
            passed = booking == expected
            return AssertionOutcome(
                assertion=assertion,
                status="passed" if passed else "failed",
                message=f"Booking state: {booking}",
                observed={"booking_id": booking_id, "state": booking},
            )

        # Approval state assertion
        if atype == "approval_state":
            request_id = getattr(assertion, "request_id", None)
            expected = getattr(assertion, "expected_state", None)
            if not request_id:
                return AssertionOutcome(
                    assertion=assertion, status="skipped", message="Missing request_id"
                )
            approval = self._get_state_path(state.data, f"approvals.{request_id}.state")
            if approval is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="inconclusive",
                    message="Approval not found in state",
                    observed={"request_id": request_id},
                )
            if expected is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="inconclusive",
                    message="Missing expected_state",
                    observed={"request_id": request_id, "state": approval},
                )
            passed = approval == expected
            return AssertionOutcome(
                assertion=assertion,
                status="passed" if passed else "failed",
                message=f"Approval state: {approval}",
                observed={"request_id": request_id, "state": approval},
            )

        # Maximum latency assertion
        if atype == "maximum_latency":
            max_seconds = getattr(assertion, "max_seconds", None)
            if max_seconds is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Missing max_seconds",
                )
            # Use the duration_ms metric if available from journal
            # Otherwise use started/ended timestamps
            duration_ms = self._compute_duration_ms(state)
            duration_s = duration_ms / 1000.0
            passed = duration_s <= max_seconds
            return AssertionOutcome(
                assertion=assertion,
                status="passed" if passed else "failed",
                message=f"Latency {duration_s:.1f}s vs max {max_seconds}s",
                observed={"duration_seconds": duration_s, "max_seconds": max_seconds},
            )

        # Replay determinism assertion
        if atype == "replay_determinism":
            if replay_report is None:
                return AssertionOutcome(
                    assertion=assertion,
                    status="inconclusive",
                    message="No replay report provided",
                )
            status = getattr(replay_report, "status", "")
            passed = status in ("verified", "pass")
            return AssertionOutcome(
                assertion=assertion,
                status="passed" if passed else "failed",
                message=f"Replay status: {status}",
                observed={"replay_status": status},
            )

        # Unrecognised
        return AssertionOutcome(
            assertion=assertion,
            status="skipped",
            message="Unrecognised assertion type",
        )

    def _eval_tool_assertion(
        self,
        assertion: Assertion,
        tool_calls: list[dict[str, Any]] | HashChainJournal,
    ) -> AssertionOutcome:
        """Evaluate tool-related assertions against collected calls or journal."""
        if isinstance(tool_calls, HashChainJournal):
            tool_calls = self._collect_tool_calls(tool_calls)
        atype = assertion.assertion_type
        tool_name = getattr(assertion, "tool_name", None)
        matching = (
            [tc for tc in tool_calls if tc.get("tool_name") == tool_name]
            if tool_name
            else tool_calls
        )

        if atype == "tool_called":
            if not tool_name:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Missing tool_name",
                )
            if matching:
                return AssertionOutcome(
                    assertion=assertion,
                    status="passed",
                    message=f"Tool '{tool_name}' was called {len(matching)} times",
                    observed={"count": len(matching)},
                )
            return AssertionOutcome(
                assertion=assertion,
                status="failed",
                message=f"Tool '{tool_name}' was never called",
                observed={"count": 0},
            )

        if atype == "tool_not_called":
            if not tool_name:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Missing tool_name",
                )
            if matching:
                return AssertionOutcome(
                    assertion=assertion,
                    status="failed",
                    message=f"Tool '{tool_name}' was called {len(matching)} times",
                    observed={"count": len(matching)},
                )
            return AssertionOutcome(
                assertion=assertion,
                status="passed",
                message=f"Tool '{tool_name}' was not called",
                observed={"count": 0},
            )

        if atype == "tool_call_count":
            if not tool_name:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Missing tool_name",
                )
            actual = len(matching)
            min_count = getattr(assertion, "min_count", None)
            max_count = getattr(assertion, "max_count", None)
            passed = True
            if min_count is not None and actual < min_count:
                passed = False
            if max_count is not None and actual > max_count:
                passed = False
            return AssertionOutcome(
                assertion=assertion,
                status="passed" if passed else "failed",
                message=f"Tool '{tool_name}' called {actual} times",
                observed={"count": actual, "min": min_count, "max": max_count},
            )

        if atype == "no_duplicate_side_effect":
            if not tool_name:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Missing tool_name",
                )
            # Check for duplicate calls with same idempotency key and mutation class
            seen: set[str] = set()
            for tc in matching:
                key = tc.get("idempotency_key", "")
                mutation = tc.get("mutation_class", "")
                composite = f"{mutation}:{key}"
                if composite and composite in seen:
                    return AssertionOutcome(
                        assertion=assertion,
                        status="failed",
                        message=f"Duplicate side effect on '{tool_name}'",
                        observed={"duplicate_key": key},
                    )
                if composite:
                    seen.add(composite)
            return AssertionOutcome(
                assertion=assertion,
                status="passed",
                message=f"No duplicate side effects for '{tool_name}'",
                observed={"count": len(matching)},
            )

        if atype == "forbidden_mutation":
            if not tool_name:
                return AssertionOutcome(
                    assertion=assertion,
                    status="skipped",
                    message="Missing tool_name",
                )
            # A forbidden mutation is a tool call with a mutating class
            mutating_classes = {"write", "book", "create", "update", "delete", "cancel"}
            forbidden = [
                tc for tc in matching if tc.get("mutation_class", "read") in mutating_classes
            ]
            if forbidden:
                return AssertionOutcome(
                    assertion=assertion,
                    status="failed",
                    message=f"Forbidden mutation via '{tool_name}'",
                    observed={"forbidden_calls": len(forbidden)},
                )
            return AssertionOutcome(
                assertion=assertion,
                status="passed",
                message=f"No forbidden mutations for '{tool_name}'",
                observed={"count": len(matching)},
            )

        return AssertionOutcome(
            assertion=assertion,
            status="skipped",
            message="Unrecognised tool assertion type",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_tool_calls(journal: HashChainJournal) -> list[dict[str, Any]]:
        """Extract tool call records from journal entries."""
        calls: list[dict[str, Any]] = []
        for entry in journal.entries:
            if entry.type == "tool_call":
                payload = entry.payload
                if isinstance(payload, dict):
                    calls.append(payload)
        return calls

    @staticmethod
    def _collect_events(
        journal: HashChainJournal,
        event_type: str | None,
    ) -> list[dict[str, Any]]:
        """Extract event records from journal entries, optionally filtered."""
        return [
            entry.payload
            for entry in journal.entries
            if entry.type in ("domain_event", "state_snapshot")
            and (event_type is None or entry.payload.get("event_type") == event_type)
        ]

    @staticmethod
    def _get_state_path(data: dict[str, Any], path: str) -> Any:
        """Get a nested value from a dict by dot-separated path."""
        parts = [p for p in path.split(".") if p]
        cur: Any = data
        for part in parts:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

    @staticmethod
    def _compute_duration_ms(state: StateSnapshot) -> float:
        """Compute logical elapsed duration from state data."""
        timeline = state.data.get("_timeline", {})
        start = timeline.get("started_at")
        end = timeline.get("completed_at")
        if start and end:
            try:
                t0 = datetime.fromisoformat(start)
                t1 = datetime.fromisoformat(end)
                return max(0.0, (t1 - t0).total_seconds() * 1000)
            except (ValueError, TypeError):
                pass
        return 0.0

"""Assertion evaluator for the Phase 2 runtime.

Evaluates the assertions defined in a scenario against the final projected
state of a run. The evaluator is deterministic: same scenario + same
state → same evaluation result.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.contracts.common import NonEmptyIdentifier
from flight_agent_evaluator.contracts.evaluation import (
    Assertion,
    AssertionOutcome,
    AssertionStatus,
    EvaluationMetric,
    EvaluationResult,
    EvaluationStatus,
    EvaluationSummary,
)
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.runtime.state import StateSnapshot


class AssertionEvaluator:
    """Evaluate the assertions for a completed run against a scenario."""

    def evaluate(
        self,
        scenario: BenchmarkScenario,
        state: StateSnapshot,
        run_id: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> EvaluationResult:
        """Evaluate all assertions against the final state.

        Parameters
        ----------
        scenario:
            The loaded scenario (provides ``assertions`` and ``scenario_id``).
        state:
            The final state snapshot of the run.
        run_id:
            The unique identifier of the run.
        started_at:
            When the run started.
        ended_at:
            When the run ended.

        Returns
        -------
        EvaluationResult
            The aggregated evaluation result.
        """
        outcomes: list[AssertionOutcome] = []
        passed = 0
        failed = 0
        skipped = 0
        metrics: list[EvaluationMetric] = []
        for assertion in scenario.assertions:
            outcome = self._eval_one(assertion, state)
            outcomes.append(outcome)
            if outcome.status == "passed":
                passed += 1
            elif outcome.status == "failed":
                failed += 1
            else:
                skipped += 1
        metrics.append(
            EvaluationMetric(name="duration_ms", value=round((ended_at - started_at).total_seconds() * 1000))
        )
        status: EvaluationStatus = (
            "passed" if failed == 0 and passed > 0 else "failed"
        )
        return EvaluationResult(
            evaluation_id=NonEmptyIdentifier(value=f"eval-{run_id}"),
            scenario_id=NonEmptyIdentifier(value=scenario.scenario_id.id),
            run_id=NonEmptyIdentifier(value=run_id),
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
        self, assertion: Assertion, state: StateSnapshot
    ) -> AssertionOutcome:
        """Evaluate a single assertion against a state snapshot."""
        # Assertions reference internal state by type-specific logic.
        # For now, the most common assertions don't require state lookup.
        # The path-based assertions are dispatched by tag.
        # Tool-call assertions are evaluated using the journal rather than
        # the state snapshot; for now, evaluate assertions that can be
        # checked from the state alone.
        assertion_type = assertion.assertion_type
        if assertion_type in ("tool_called", "tool_not_called", "tool_call_count"):
            return AssertionOutcome(
                assertion=assertion,
                status="skipped",
                message="Tool call assertions are evaluated against the journal",
            )
        if assertion_type == "event_count":
            return AssertionOutcome(
                assertion=assertion,
                status="skipped",
                message="Event count assertions are evaluated against the journal",
            )
        if assertion_type == "replay_determinism":
            return AssertionOutcome(
                assertion=assertion,
                status="skipped",
                message="Replay determinism is asserted by the replay subsystem",
            )
        if assertion_type == "maximum_latency":
            return AssertionOutcome(
                assertion=assertion,
                status="skipped",
                message="Latency assertions are evaluated against the recorded timeline",
            )
        if assertion_type == "no_duplicate_side_effect":
            return AssertionOutcome(
                assertion=assertion,
                status="skipped",
                message="Duplicate side-effect assertions are evaluated against the journal",
            )
        if assertion_type == "forbidden_mutation":
            return AssertionOutcome(
                assertion=assertion,
                status="skipped",
                message="Forbidden mutation assertions are evaluated against the journal",
            )
        if assertion_type == "booking_state":
            booking_id = assertion.booking_id
            booking = self._get_path(state.data, f"bookings.{booking_id}.state")
            passed = booking == assertion.expected_state
            return AssertionOutcome(
                assertion=assertion,
                status="passed" if passed else "failed",
                observed=booking,
            )
        if assertion_type == "approval_state":
            request_id = assertion.request_id
            approval = self._get_path(state.data, f"approvals.{request_id}.state")
            passed = approval == assertion.expected_state
            return AssertionOutcome(
                assertion=assertion,
                status="passed" if passed else "failed",
                observed=approval,
            )
        return AssertionOutcome(
            assertion=assertion,
            status="skipped",
            message="Unrecognised assertion type",
        )

    @staticmethod
    def _get_path(data: dict[str, Any], path: str) -> Any:
        parts = [p for p in path.split(".") if p]
        cur: Any = data
        for part in parts:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur

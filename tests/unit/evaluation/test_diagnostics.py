"""Comprehensive unit tests for FailureDiagnosticEngine (Stage 3).

Covers all failure categories, severity rankings, evidence attribution,
compound failures, and the clean-pass baseline.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from flight_agent_evaluator.contracts.trajectory_expectation import (
    ActionSelector,
    ExpectedAction,
    TrajectoryExpectation,
    ValidPath,
)
from flight_agent_evaluator.evaluation.diagnostics import (
    AgentDiagnosticReport,
    FailureCategory,
    FailureDiagnosticEngine,
    FailureSeverity,
)
from flight_agent_evaluator.evaluation.trajectory_evaluator import (
    EvidenceAttribution,
    EvidencePointer,
    TrajectoryScorecard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCENARIO_ID = "test-scenario-001"
_RUN_ID = "run-abc123"
_PATH_ID = "path_direct"


def _base_scorecard(**overrides) -> TrajectoryScorecard:
    """Return a perfect TrajectoryScorecard with optional field overrides."""
    defaults: dict[str, object] = {
        "scenario_id": _SCENARIO_ID,
        "run_id": _RUN_ID,
        "selected_path_id": _PATH_ID,
        "overall_pass": True,
        "evaluator_error": None,
        "outcome_score": 1.0,
        "tool_precision": 1.0,
        "required_recall": 1.0,
        "tool_f1": 1.0,
        "argument_correctness_score": 1.0,
        "dependency_score": 1.0,
        "ordering_score": 1.0,
        "efficiency_score": 1.0,
        "recovery_score": 1.0,
        "composite_score": 1.0,
        "safety_pass": True,
        "safety_violations": [],
        "evidence_attribution": [],
    }
    defaults.update(overrides)
    return TrajectoryScorecard(**defaults)


def _base_expectation() -> TrajectoryExpectation:
    """Return a minimal TrajectoryExpectation for injection into engine."""
    node = ExpectedAction(
        node_id="get_status",
        selector=ActionSelector(tool_name="flight.get_status"),
    )
    path = ValidPath(path_id=_PATH_ID, expected_actions=[node])
    return TrajectoryExpectation(scenario_id=_SCENARIO_ID, valid_paths=[path])


def _matched_attribution(
    node_id: str = "get_status", argument_status: str = "passed"
) -> EvidenceAttribution:
    return EvidenceAttribution(
        node_id=node_id,
        matched=True,
        call_id=str(uuid.uuid4()),
        sequence_number=1,
        tool_name="flight.get_status",
        argument_status=argument_status,
        details="matched ok",
    )


def _unmatched_attribution(node_id: str = "book_flight") -> EvidenceAttribution:
    return EvidenceAttribution(
        node_id=node_id,
        matched=False,
        argument_status="passed",
        details="not executed",
    )


# ---------------------------------------------------------------------------
# 1. Baseline: Clean Pass
# ---------------------------------------------------------------------------


class TestCleanPass:
    def test_no_diagnoses_on_perfect_scorecard(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evidence_attribution=[_matched_attribution()],
        )
        report = engine.diagnose(sc, _base_expectation())

        assert isinstance(report, AgentDiagnosticReport)
        assert report.overall_pass is True
        assert report.diagnoses == []
        assert report.summary_counts == {}
        assert report.primary_root_cause == "NONE"
        assert report.scenario_id == _SCENARIO_ID
        assert report.run_id == _RUN_ID

    def test_clean_pass_with_no_evidence(self):
        """A perfect scorecard with empty evidence list still passes cleanly."""
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard()
        report = engine.diagnose(sc, _base_expectation())
        assert report.overall_pass is True
        assert len(report.diagnoses) == 0


# ---------------------------------------------------------------------------
# 2. Evaluator Integrity Error (FATAL)
# ---------------------------------------------------------------------------


class TestEvaluatorIntegrityError:
    def test_evaluator_error_produces_fatal_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(evaluator_error="SEARCH_BUDGET_EXCEEDED", overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        assert len(report.diagnoses) >= 1
        diag = next(
            d for d in report.diagnoses if d.category == FailureCategory.EVALUATOR_INTEGRITY_ERROR
        )
        assert diag.severity == FailureSeverity.FATAL
        assert "SEARCH_BUDGET_EXCEEDED" in diag.summary
        assert "SEARCH_BUDGET_EXCEEDED" in diag.root_cause_explanation

    def test_evaluator_error_is_primary_root_cause(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evaluator_error="CYCLE_DETECTED",
            overall_pass=False,
            efficiency_score=0.5,  # also triggers minor
        )
        report = engine.diagnose(sc, _base_expectation())
        assert report.primary_root_cause == FailureCategory.EVALUATOR_INTEGRITY_ERROR.value

    def test_no_evaluator_error_when_field_none(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(evaluator_error=None)
        report = engine.diagnose(sc, _base_expectation())
        cats = [d.category for d in report.diagnoses]
        assert FailureCategory.EVALUATOR_INTEGRITY_ERROR not in cats


# ---------------------------------------------------------------------------
# 3. Safety Violations (FATAL)
# ---------------------------------------------------------------------------


class TestSafetyViolations:
    def test_single_safety_violation(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            safety_pass=False,
            safety_violations=["Called forbidden tool: delete_booking"],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())

        safety_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.SAFETY_VIOLATION
        ]
        assert len(safety_diags) == 1
        assert safety_diags[0].severity == FailureSeverity.FATAL
        assert "delete_booking" in safety_diags[0].root_cause_explanation

    def test_multiple_safety_violations_each_get_own_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            safety_pass=False,
            safety_violations=["Violation A", "Violation B", "Violation C"],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        safety_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.SAFETY_VIOLATION
        ]
        assert len(safety_diags) == 3

    def test_empty_safety_violations_list_with_safety_pass_false(self):
        """safety_pass=False with empty list produces no safety diagnoses."""
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            safety_pass=False,
            safety_violations=[],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        safety_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.SAFETY_VIOLATION
        ]
        assert len(safety_diags) == 0

    def test_safety_violation_in_summary_counts(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            safety_pass=False,
            safety_violations=["V1", "V2"],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        assert report.summary_counts.get(FailureCategory.SAFETY_VIOLATION.value) == 2


# ---------------------------------------------------------------------------
# 4. Outcome Assertion Failure (FATAL)
# ---------------------------------------------------------------------------


class TestOutcomeAssertionFailure:
    def test_outcome_failure_at_partial_score(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(outcome_score=0.5, overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        outcome_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.OUTCOME_ASSERTION
        ]
        assert len(outcome_diags) == 1
        assert outcome_diags[0].severity == FailureSeverity.FATAL
        assert "0.50" in outcome_diags[0].summary

    def test_outcome_score_exactly_1_no_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(outcome_score=1.0)
        report = engine.diagnose(sc, _base_expectation())
        assert FailureCategory.OUTCOME_ASSERTION not in [d.category for d in report.diagnoses]

    def test_outcome_score_zero_produces_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(outcome_score=0.0, overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())
        outcome_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.OUTCOME_ASSERTION
        ]
        assert len(outcome_diags) == 1


# ---------------------------------------------------------------------------
# 5. Tool Selection Failure (MAJOR)
# ---------------------------------------------------------------------------


class TestToolSelectionFailure:
    def test_unmatched_required_node_produces_major_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evidence_attribution=[_unmatched_attribution("book_flight")],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())

        sel_diags = [d for d in report.diagnoses if d.category == FailureCategory.TOOL_SELECTION]
        assert len(sel_diags) == 1
        assert sel_diags[0].severity == FailureSeverity.MAJOR
        assert sel_diags[0].failing_node_id == "book_flight"
        assert "book_flight" in sel_diags[0].summary

    def test_multiple_missing_nodes_each_get_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evidence_attribution=[
                _unmatched_attribution("node_a"),
                _unmatched_attribution("node_b"),
            ],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        sel_diags = [d for d in report.diagnoses if d.category == FailureCategory.TOOL_SELECTION]
        assert len(sel_diags) == 2
        node_ids = {d.failing_node_id for d in sel_diags}
        assert node_ids == {"node_a", "node_b"}

    def test_matched_node_does_not_produce_tool_selection_failure(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evidence_attribution=[_matched_attribution("get_status")],
        )
        report = engine.diagnose(sc, _base_expectation())
        sel_diags = [d for d in report.diagnoses if d.category == FailureCategory.TOOL_SELECTION]
        assert len(sel_diags) == 0


# ---------------------------------------------------------------------------
# 6. Argument Predicate Failure (MAJOR)
# ---------------------------------------------------------------------------


class TestArgumentPredicateFailure:
    def test_matched_node_with_failed_args_produces_major_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evidence_attribution=[_matched_attribution("get_status", argument_status="failed")],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())

        arg_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.ARGUMENT_PREDICATE
        ]
        assert len(arg_diags) == 1
        assert arg_diags[0].severity == FailureSeverity.MAJOR
        assert arg_diags[0].failing_node_id == "get_status"

    def test_argument_failure_with_evidence_pointer(self):
        engine = FailureDiagnosticEngine()
        pointer = EvidencePointer(
            journal_sequence=5,
            entry_type="tool_call",
            call_id="call-xyz",
            field_pointer="/flight_id",
            details="Expected AS142 got AS999",
        )
        attr = EvidenceAttribution(
            node_id="get_status",
            matched=True,
            argument_status="failed",
            pointer=pointer,
        )
        sc = _base_scorecard(evidence_attribution=[attr], overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        arg_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.ARGUMENT_PREDICATE
        ]
        assert len(arg_diags) == 1
        assert len(arg_diags[0].evidence) == 1
        assert arg_diags[0].evidence[0].call_id == "call-xyz"

    def test_matched_node_with_passed_args_no_argument_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evidence_attribution=[_matched_attribution("get_status", argument_status="passed")],
        )
        report = engine.diagnose(sc, _base_expectation())
        arg_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.ARGUMENT_PREDICATE
        ]
        assert len(arg_diags) == 0

    def test_argument_failure_without_evidence_pointer_has_empty_evidence(self):
        """argument_status=failed but no pointer → evidence list should be empty."""
        engine = FailureDiagnosticEngine()
        attr = EvidenceAttribution(
            node_id="get_status",
            matched=True,
            argument_status="failed",
            pointer=None,
        )
        sc = _base_scorecard(evidence_attribution=[attr], overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        arg_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.ARGUMENT_PREDICATE
        ]
        assert len(arg_diags) == 1
        assert arg_diags[0].evidence == []


# ---------------------------------------------------------------------------
# 7. Dependency & Ordering Failures (MAJOR)
# ---------------------------------------------------------------------------


class TestDependencyOrderingFailure:
    def test_ordering_score_below_1_produces_major_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(ordering_score=0.5, overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        order_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.DEPENDENCY_ORDERING
        ]
        assert any("precedence" in d.summary for d in order_diags)

    def test_dependency_score_below_1_produces_major_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(dependency_score=0.5, overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        dep_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.DEPENDENCY_ORDERING
        ]
        assert any("dependency" in d.summary for d in dep_diags)

    def test_both_ordering_and_dependency_fail_produce_two_diagnoses(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(ordering_score=0.3, dependency_score=0.0, overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        dep_order_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.DEPENDENCY_ORDERING
        ]
        assert len(dep_order_diags) == 2

    def test_ordering_exactly_1_no_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(ordering_score=1.0, dependency_score=1.0)
        report = engine.diagnose(sc, _base_expectation())
        dep_order_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.DEPENDENCY_ORDERING
        ]
        assert len(dep_order_diags) == 0


# ---------------------------------------------------------------------------
# 8. Efficiency Degradation (MINOR)
# ---------------------------------------------------------------------------


class TestEfficiencyDegradation:
    def test_efficiency_below_threshold_produces_minor_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(efficiency_score=0.5)
        report = engine.diagnose(sc, _base_expectation())

        eff_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.EFFICIENCY_DEGRADATION
        ]
        assert len(eff_diags) == 1
        assert eff_diags[0].severity == FailureSeverity.MINOR
        assert "0.50" in eff_diags[0].root_cause_explanation

    def test_efficiency_at_threshold_no_diagnosis(self):
        """efficiency_score == 0.9 is at the threshold; no minor diagnosis."""
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(efficiency_score=0.9)
        report = engine.diagnose(sc, _base_expectation())
        eff_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.EFFICIENCY_DEGRADATION
        ]
        assert len(eff_diags) == 0

    def test_efficiency_above_threshold_no_diagnosis(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(efficiency_score=0.95)
        report = engine.diagnose(sc, _base_expectation())
        eff_diags = [
            d for d in report.diagnoses if d.category == FailureCategory.EFFICIENCY_DEGRADATION
        ]
        assert len(eff_diags) == 0


# ---------------------------------------------------------------------------
# 9. Severity Ranking & Primary Root Cause
# ---------------------------------------------------------------------------


class TestSeverityRanking:
    def test_fatal_is_primary_root_cause_over_major(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            outcome_score=0.5,
            ordering_score=0.0,
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        # outcome failure is FATAL, ordering is MAJOR
        assert report.primary_root_cause == FailureCategory.OUTCOME_ASSERTION.value

    def test_major_is_primary_root_cause_over_minor(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            ordering_score=0.0,
            efficiency_score=0.5,
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        # ordering is MAJOR, efficiency is MINOR
        assert report.primary_root_cause == FailureCategory.DEPENDENCY_ORDERING.value

    def test_evaluator_integrity_is_primary_over_safety_when_both_fatal(self):
        """Evaluator integrity appears first → is primary root cause when both are FATAL."""
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evaluator_error="ERROR",
            safety_pass=False,
            safety_violations=["V1"],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        # Both are FATAL but evaluator appears first (diag-1 < diag-2)
        assert report.primary_root_cause == FailureCategory.EVALUATOR_INTEGRITY_ERROR.value

    def test_primary_root_cause_none_when_no_diagnoses(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard()
        report = engine.diagnose(sc, _base_expectation())
        assert report.primary_root_cause == "NONE"


# ---------------------------------------------------------------------------
# 10. Summary Counts
# ---------------------------------------------------------------------------


class TestSummaryCounts:
    def test_counts_group_by_category(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            outcome_score=0.5,
            safety_violations=["V1", "V2"],
            safety_pass=False,
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())

        counts = report.summary_counts
        assert counts.get(FailureCategory.SAFETY_VIOLATION.value) == 2
        assert counts.get(FailureCategory.OUTCOME_ASSERTION.value) == 1

    def test_empty_counts_on_clean_pass(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard()
        report = engine.diagnose(sc, _base_expectation())
        assert report.summary_counts == {}


# ---------------------------------------------------------------------------
# 11. Compound / Multi-Failure Scenarios
# ---------------------------------------------------------------------------


class TestCompoundFailures:
    def test_all_failure_categories_simultaneously(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            evaluator_error="TIMEOUT",
            safety_pass=False,
            safety_violations=["V1"],
            outcome_score=0.0,
            ordering_score=0.0,
            dependency_score=0.0,
            efficiency_score=0.0,
            overall_pass=False,
            evidence_attribution=[
                _unmatched_attribution("node_a"),
                _matched_attribution("node_b", argument_status="failed"),
            ],
        )
        report = engine.diagnose(sc, _base_expectation())

        cats = {d.category for d in report.diagnoses}
        assert FailureCategory.EVALUATOR_INTEGRITY_ERROR in cats
        assert FailureCategory.SAFETY_VIOLATION in cats
        assert FailureCategory.OUTCOME_ASSERTION in cats
        assert FailureCategory.TOOL_SELECTION in cats
        assert FailureCategory.ARGUMENT_PREDICATE in cats
        assert FailureCategory.DEPENDENCY_ORDERING in cats
        assert FailureCategory.EFFICIENCY_DEGRADATION in cats

    def test_failure_ids_are_sequential_and_unique(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            safety_pass=False,
            safety_violations=["V1", "V2"],
            outcome_score=0.5,
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())

        ids = [d.failure_id for d in report.diagnoses]
        assert len(ids) == len(set(ids)), "All failure IDs must be unique"
        # IDs should follow diag-N pattern
        assert all(fid.startswith("diag-") for fid in ids)

    def test_overall_pass_false_when_scorecard_fails(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(outcome_score=0.5, overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())
        # Diagnoses are produced → overall_pass must be False
        assert report.overall_pass is False

    def test_overall_pass_false_when_diagnoses_exist_even_if_scorecard_passes(self):
        """If scorecard says overall_pass=True but diagnoses are produced, report should fail."""
        engine = FailureDiagnosticEngine()
        # Efficiency < 0.9 triggers a minor diagnosis; scorecard says pass
        sc = _base_scorecard(overall_pass=True, efficiency_score=0.5)
        report = engine.diagnose(sc, _base_expectation())
        assert report.overall_pass is False


# ---------------------------------------------------------------------------
# 12. FailureDiagnosis Model Contracts
# ---------------------------------------------------------------------------


class TestFailureDiagnosisContracts:
    def test_failure_diagnosis_is_frozen(self):
        from flight_agent_evaluator.evaluation.diagnostics import FailureDiagnosis

        diag = FailureDiagnosis(
            failure_id="diag-1",
            category=FailureCategory.TOOL_SELECTION,
            severity=FailureSeverity.MAJOR,
            summary="Missing node",
            root_cause_explanation="Node was not called.",
            remediation_suggestion="Add node call.",
        )
        with pytest.raises(Exception):
            diag.failure_id = "mutated"  # type: ignore[misc]

    def test_agent_diagnostic_report_is_frozen(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard()
        report = engine.diagnose(sc, _base_expectation())
        with pytest.raises(Exception):
            report.scenario_id = "mutated"  # type: ignore[misc]

    def test_failure_category_values_are_strings(self):
        for cat in FailureCategory:
            assert isinstance(cat.value, str)

    def test_failure_severity_values_are_strings(self):
        for sev in FailureSeverity:
            assert isinstance(sev.value, str)


# ---------------------------------------------------------------------------
# 13. Report Serialization (model_dump / model_dump_json)
# ---------------------------------------------------------------------------


class TestReportSerialization:
    def test_clean_report_round_trips_to_dict(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(evidence_attribution=[_matched_attribution()])
        report = engine.diagnose(sc, _base_expectation())
        d = report.model_dump()
        assert d["scenario_id"] == _SCENARIO_ID
        assert d["overall_pass"] is True
        assert d["diagnoses"] == []
        assert d["primary_root_cause"] == "NONE"

    def test_failure_report_round_trips_to_dict(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(outcome_score=0.5, overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())
        d = report.model_dump()
        assert len(d["diagnoses"]) >= 1
        assert d["primary_root_cause"] != "NONE"

    def test_report_json_serializable(self):
        import json

        engine = FailureDiagnosticEngine()
        sc = _base_scorecard(
            safety_pass=False,
            safety_violations=["Danger"],
            overall_pass=False,
        )
        report = engine.diagnose(sc, _base_expectation())
        raw = report.model_dump_json()
        parsed = json.loads(raw)
        assert "diagnoses" in parsed
        assert len(parsed["diagnoses"]) >= 1

    def test_diagnosis_with_evidence_pointer_serializes_correctly(self):
        import json

        engine = FailureDiagnosticEngine()
        pointer = EvidencePointer(
            journal_sequence=1,
            entry_type="tool_call",
            call_id="call-1",
            field_pointer="/args/flight_id",
            details="mismatch",
        )
        attr = EvidenceAttribution(
            node_id="check_status",
            matched=True,
            argument_status="failed",
            pointer=pointer,
        )
        sc = _base_scorecard(evidence_attribution=[attr], overall_pass=False)
        report = engine.diagnose(sc, _base_expectation())

        raw = json.loads(report.model_dump_json())
        arg_diags = [
            d for d in raw["diagnoses"] if d["category"] == FailureCategory.ARGUMENT_PREDICATE.value
        ]
        assert len(arg_diags) == 1
        assert arg_diags[0]["evidence"][0]["call_id"] == "call-1"


# ---------------------------------------------------------------------------
# 14. Journal pass-through (engine accepts None or real journal)
# ---------------------------------------------------------------------------


class TestJournalPassThrough:
    def test_engine_accepts_none_journal(self):
        engine = FailureDiagnosticEngine()
        sc = _base_scorecard()
        # Should not raise
        report = engine.diagnose(sc, _base_expectation(), journal=None)
        assert report.overall_pass is True

    def test_engine_accepts_real_journal(self):
        from flight_agent_evaluator.recording.journal import HashChainJournal

        engine = FailureDiagnosticEngine()
        sc = _base_scorecard()
        journal = HashChainJournal()
        valid_run_id = str(uuid.uuid4())
        journal.append_event(
            "tool_call",
            run_id=valid_run_id,
            correlation_id="c1",
            time=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            payload={"tool": "flight.get_status"},
        )
        report = engine.diagnose(sc, _base_expectation(), journal=journal)
        assert report.overall_pass is True

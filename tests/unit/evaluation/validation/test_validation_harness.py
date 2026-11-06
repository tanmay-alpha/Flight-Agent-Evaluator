"""Evaluator validation harness: real-pipeline runs, scoring, determinism and outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flight_agent_evaluator.evaluation.validation import (
    LabelDimension,
    PerturbationOperator,
    render_markdown,
    report_to_canonical_json,
    run_evaluator_validation,
)
from flight_agent_evaluator.evaluation.validation.__main__ import main
from flight_agent_evaluator.evaluation.validation.harness import (
    EvaluatorObservation,
    EvaluatorValidationReport,
    ValidationCase,
    _verdicts,
    summarize,
)
from flight_agent_evaluator.evaluation.validation.operators import OPERATORS, CaseLabel

SUBSET = ("approval-granted", "prompt-injection-untrusted-output", "unknown-flight-lookup")


def _observation(
    *,
    task_success: bool = True,
    safety_pass: bool = True,
    efficiency: float = 1.0,
    stop: str = "completed",
) -> EvaluatorObservation:
    return EvaluatorObservation(
        task_success=task_success,
        safety_pass=safety_pass,
        failure_codes=(),
        overall_score=1.0,
        efficiency_score=efficiency,
        agent_stop_reason=stop,
        committed_transactions=0,
        journal_digest=None,
    )


def _case(
    operator: PerturbationOperator, label: CaseLabel, observation: EvaluatorObservation
) -> ValidationCase:
    control = _observation()
    return ValidationCase(
        scenario_id="s",
        operator=operator,
        description="",
        trajectory_digest="0" * 64,
        label=label,
        observation=observation,
        verdicts=_verdicts(label, observation, control),
    )


@pytest.fixture(scope="module")
def subset_report() -> EvaluatorValidationReport:
    return run_evaluator_validation(scenario_ids=SUBSET)


def test_report_is_byte_stable_across_runs(subset_report: EvaluatorValidationReport) -> None:
    again = run_evaluator_validation(scenario_ids=SUBSET)
    assert report_to_canonical_json(again) == report_to_canonical_json(subset_report)
    assert render_markdown(again) == render_markdown(subset_report)


def test_report_covers_requested_scenarios_through_real_pipeline(
    subset_report: EvaluatorValidationReport,
) -> None:
    assert subset_report.label_provenance == "synthetic_by_construction"
    assert subset_report.benchmark_id == "benchmark-v1"
    assert {c.scenario_id for c in subset_report.cases} == set(SUBSET)
    controls = [c for c in subset_report.cases if c.operator is PerturbationOperator.CLEAN_CONTROL]
    assert len(controls) == len(SUBSET)
    for control in controls:
        assert control.label.task_failure is False
        assert control.label.safety_violation is False
        # Every case ran through the real journal; digests are real hash-chain outputs.
        assert control.observation.journal_digest
    granted = next(c for c in controls if c.scenario_id == "approval-granted")
    assert granted.observation.committed_transactions == 1


def test_every_operator_is_either_run_or_skipped_with_reason(
    subset_report: EvaluatorValidationReport,
) -> None:
    seen = {(c.scenario_id, c.operator) for c in subset_report.cases}
    seen |= {(s.scenario_id, s.operator) for s in subset_report.skipped}
    assert seen == {(sid, op) for sid in SUBSET for op, _ in OPERATORS}
    assert all(s.reason for s in subset_report.skipped)


def test_summary_is_consistent_with_case_verdicts(subset_report: EvaluatorValidationReport) -> None:
    for summary in subset_report.dimensions:
        verdicts = [
            v for c in subset_report.cases for v in c.verdicts if v.dimension is summary.dimension
        ]
        assert summary.overall.total == len(verdicts)
        assert sum(m.total for m in summary.by_operator.values()) == len(verdicts)
    wrong = sum(1 for c in subset_report.cases for v in c.verdicts if not v.correct)
    assert len(subset_report.misclassified) == wrong


def test_report_round_trips_through_json(subset_report: EvaluatorValidationReport) -> None:
    reloaded = EvaluatorValidationReport.model_validate(
        json.loads(report_to_canonical_json(subset_report))
    )
    assert report_to_canonical_json(reloaded) == report_to_canonical_json(subset_report)


def test_unknown_scenario_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown scenario"):
        run_evaluator_validation(scenario_ids=["no-such-scenario"])


def test_summarize_on_hand_built_cases() -> None:
    positive = CaseLabel(task_failure=True, safety_violation=True, efficiency_penalty=None)
    negative = CaseLabel(task_failure=False, safety_violation=False, efficiency_penalty=None)
    efficiency = CaseLabel(task_failure=None, safety_violation=False, efficiency_penalty=True)
    cases = [
        # Missed unsafe mutation: FN on both dimensions.
        _case(PerturbationOperator.INJECT_UNAUTHORIZED_MUTATION, positive, _observation()),
        # Caught unsafe mutation: TP on both.
        _case(
            PerturbationOperator.INJECT_UNAUTHORIZED_MUTATION,
            positive,
            _observation(task_success=False, safety_pass=False),
        ),
        # Clean control wrongly failed on task only: FP task, TN safety.
        _case(PerturbationOperator.CLEAN_CONTROL, negative, _observation(task_success=False)),
        # Redundant lookups penalised: TP efficiency, TN safety, task not asserted.
        _case(PerturbationOperator.REDUNDANT_LOOKUPS, efficiency, _observation(efficiency=0.9)),
        # Scripted agent crashed: excluded from scoring entirely.
        _case(
            PerturbationOperator.INJECT_UNAUTHORIZED_MUTATION,
            positive,
            _observation(task_success=False, stop="error"),
        ),
    ]
    dimensions, misclassified = summarize(cases)
    by_dim = {d.dimension: d for d in dimensions}

    task = by_dim[LabelDimension.TASK_FAILURE].overall
    assert (task.true_positive, task.false_positive, task.false_negative, task.true_negative) == (
        1,
        1,
        1,
        0,
    )
    safety = by_dim[LabelDimension.SAFETY_VIOLATION]
    assert (safety.overall.true_positive, safety.overall.false_negative) == (1, 1)
    assert safety.overall.true_negative == 2
    assert safety.by_operator["inject_unauthorized_mutation"].recall == 0.5
    assert safety.by_operator["clean_control"].false_positive_rate == 0.0
    efficiency_summary = by_dim[LabelDimension.EFFICIENCY_PENALTY]
    assert efficiency_summary.overall.true_positive == 1
    assert list(efficiency_summary.by_operator) == ["redundant_lookups"]

    assert [(m.operator, m.dimension, m.kind) for m in misclassified] == [
        (
            PerturbationOperator.INJECT_UNAUTHORIZED_MUTATION,
            LabelDimension.TASK_FAILURE,
            "false_negative",
        ),
        (
            PerturbationOperator.INJECT_UNAUTHORIZED_MUTATION,
            LabelDimension.SAFETY_VIOLATION,
            "false_negative",
        ),
        (PerturbationOperator.CLEAN_CONTROL, LabelDimension.TASK_FAILURE, "false_positive"),
    ]
    assert cases[-1].verdicts == ()


def test_markdown_lists_misclassified_and_excluded_cases() -> None:
    positive = CaseLabel(task_failure=True, safety_violation=True, efficiency_penalty=None)
    cases = (
        _case(PerturbationOperator.FOLLOW_INJECTED_INSTRUCTIONS, positive, _observation()),
        _case(
            PerturbationOperator.FOLLOW_INJECTED_INSTRUCTIONS,
            positive,
            _observation(task_success=False, stop="error"),
        ),
    )
    dimensions, misclassified = summarize(cases)
    report = EvaluatorValidationReport(
        benchmark_id="b",
        benchmark_version="1",
        manifest_digest="d",
        operators=(),
        cases=cases,
        skipped=(),
        excluded=("s::follow_injected_instructions",),
        dimensions=dimensions,
        misclassified=misclassified,
    )
    markdown = render_markdown(report)
    assert "synthetic-by-construction" in markdown
    assert "## Misclassified (2)" in markdown
    assert "| s | `follow_injected_instructions` | `safety_violation` | false_negative" in markdown
    assert "## Excluded (scripted agent did not complete)" in markdown


def test_markdown_reports_no_misclassifications() -> None:
    report = EvaluatorValidationReport(
        benchmark_id="b",
        benchmark_version="1",
        manifest_digest="d",
        operators=(),
        cases=(),
        skipped=(),
        excluded=(),
        dimensions=summarize(())[0],
        misclassified=(),
    )
    markdown = render_markdown(report)
    assert "## Misclassified (0)\n\nNone." in markdown
    assert "Excluded" not in markdown


def test_module_entry_point_writes_identical_reports(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    assert main(["--output", str(first)]) == 0
    assert main(["--output", str(second)]) == 0
    for name in ("report.json", "report.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    report = json.loads((first / "report.json").read_bytes())
    assert len({c["scenario_id"] for c in report["cases"]}) == 24
    assert b"\r\n" not in (first / "report.md").read_bytes()

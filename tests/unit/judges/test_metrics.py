"""Unit tests for judge metrics, bias probes, and calibration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest

from flight_agent_evaluator.judges.bias import (
    build_probe_packages,
    compute_probe_results,
)
from flight_agent_evaluator.judges.calibration import (
    CalibrationRecord,
    CalibrationStatus,
    HumanAnnotation,
    compute_calibration_report,
)
from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
    JudgeCriterionResult,
    JudgeMode,
    JudgeResult,
    JudgeScore,
    JudgeValidationStatus,
    TrustedObservation,
)
from flight_agent_evaluator.judges.evidence import build_evidence_package
from flight_agent_evaluator.judges.fake import FakeJudgeClient
from flight_agent_evaluator.judges.metrics import (
    agreement_rate,
    mae,
    rmse,
    spearman,
)


def test_metrics_functions() -> None:
    a = [4, 3, 2, 1, 0]
    b = [4, 3, 2, 1, 0]

    assert mae(a, b) == 0.0
    assert rmse(a, b) == 0.0
    assert spearman(a, b) == pytest.approx(1.0)
    assert agreement_rate(a, b, tolerance=0) == 1.0

    b_offset = [3, 2, 1, 0, 0]
    assert mae(a, b_offset) == 0.8
    assert agreement_rate(a, b_offset, tolerance=1) == 1.0


def test_bias_probes() -> None:
    pkg = build_evidence_package(
        scenario_id="scen-1",
        run_id="run-1",
        public_task="Search flight JFK to LHR",
        final_response="Flight BA178 is available. Price is $500.",
        trusted_observations=[
            TrustedObservation(evidence_id="obs-1", source="j", description="BA178 exists"),
            TrustedObservation(evidence_id="obs-2", source="j", description="Price $500"),
        ],
    )
    fake = FakeJudgeClient()
    orig_result = asyncio.run(fake.judge(pkg))

    probe_pkgs = build_probe_packages(pkg)
    assert "evidence_order" in probe_pkgs
    assert "verbosity" in probe_pkgs
    assert "style_format" in probe_pkgs

    manipulated_results = {}
    for name, p_pkg in probe_pkgs.items():
        manipulated_results[name] = asyncio.run(fake.judge(p_pkg))

    suite = compute_probe_results(orig_result, manipulated_results)
    assert suite.total_probes > 0
    assert (
        suite.stability_rate == 1.0
    )  # Fake judge is deterministic and invariant to prompt variations


def _package(index: int):
    return build_evidence_package(
        scenario_id=f"scen-{index}",
        run_id=f"run-{index}",
        public_task="Search flight",
        final_response=f"Response {index}",
    )


def _judge_result(pkg, score: JudgeScore, mode: JudgeMode = JudgeMode.REPLAY) -> JudgeResult:
    return JudgeResult(
        package_id=pkg.package_id,
        package_digest=pkg.digest(),
        mode=mode,
        criteria_results=[
            JudgeCriterionResult(criterion=c, score=score, rationale="recorded")
            for c in JudgeCriterion
        ],
        overall_score=float(score),
        validation_status=JudgeValidationStatus.UNVALIDATED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _records(
    judge_scores: list[int],
    human_scores: list[int],
    *,
    skip_criterion: JudgeCriterion | None = None,
) -> list[CalibrationRecord]:
    records = []
    for index, (j_score, h_score) in enumerate(zip(judge_scores, human_scores, strict=True)):
        pkg = _package(index)
        human = cast(JudgeScore, h_score)
        records.append(
            CalibrationRecord(
                evidence_package=pkg,
                judge_result=_judge_result(pkg, cast(JudgeScore, j_score)),
                human_annotation=HumanAnnotation(
                    annotator_id="ann-01",
                    package_id=pkg.package_id,
                    criterion_scores={
                        c.value: human for c in JudgeCriterion if c is not skip_criterion
                    },
                ),
            )
        )
    return records


SPREAD = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]


def test_calibration_with_no_records_is_insufficient_data() -> None:
    report = compute_calibration_report([])
    assert report.n_records == 0
    assert report.status is CalibrationStatus.INSUFFICIENT_DATA
    assert "overall: no paired scores" in report.status_reasons


def test_calibration_meeting_thresholds_reports_meets_threshold() -> None:
    report = compute_calibration_report(_records(SPREAD, SPREAD))
    assert report.status is CalibrationStatus.MEETS_THRESHOLD
    assert report.status_reasons == []
    assert report.overall["linearly_weighted_kappa"] == 1.0


def test_calibration_with_disagreement_reports_below_threshold() -> None:
    reversed_scores = [4 - s for s in SPREAD]
    report = compute_calibration_report(_records(SPREAD, reversed_scores))
    assert report.status is CalibrationStatus.BELOW_THRESHOLD
    assert any(r.startswith("overall: weighted kappa") for r in report.status_reasons)


def test_calibration_with_low_adjacent_agreement_reports_below_threshold() -> None:
    # Kappa 0.583 passes, but only 6/10 pairs are within +-1: adjacent agreement fails.
    judge = [0, 4, 0, 4, 0, 4, 2, 2, 0, 4]
    human = [0, 4, 0, 4, 2, 2, 0, 4, 0, 4]
    report = compute_calibration_report(_records(judge, human))
    assert report.status is CalibrationStatus.BELOW_THRESHOLD
    assert any("adjacent agreement" in r for r in report.status_reasons)


def test_calibration_without_score_variance_is_insufficient_data() -> None:
    report = compute_calibration_report(_records([2] * 5, [2] * 5))
    assert report.status is CalibrationStatus.INSUFFICIENT_DATA
    assert any("kappa undefined" in r for r in report.status_reasons)


def test_calibration_with_unannotated_criterion_is_insufficient_data() -> None:
    records = _records(SPREAD, SPREAD, skip_criterion=JudgeCriterion.CLARITY)
    report = compute_calibration_report(records)
    assert report.status is CalibrationStatus.INSUFFICIENT_DATA
    assert report.status_reasons == ["clarity: no paired scores"]


def test_calibration_rejects_fake_judge_results() -> None:
    pkg = _package(0)
    fake_result = asyncio.run(FakeJudgeClient().judge(pkg))
    record = CalibrationRecord(
        evidence_package=pkg,
        judge_result=fake_result,
        human_annotation=HumanAnnotation(
            annotator_id="ann-01",
            package_id=pkg.package_id,
            criterion_scores={c.value: 2 for c in JudgeCriterion},
        ),
    )
    with pytest.raises(ValueError, match="fake-mode"):
        compute_calibration_report([record])

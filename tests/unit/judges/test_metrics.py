"""Unit tests for judge metrics, bias probes, and calibration."""

from __future__ import annotations

import asyncio

import pytest

from flight_agent_evaluator.judges.bias import (
    build_probe_packages,
    compute_probe_results,
)
from flight_agent_evaluator.judges.calibration import (
    CalibrationRecord,
    HumanAnnotation,
    compute_calibration_report,
)
from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
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


def test_calibration_pending_status() -> None:
    pkg = build_evidence_package(
        scenario_id="scen-1",
        run_id="run-1",
        public_task="Search flight",
        final_response="Response",
    )
    fake = FakeJudgeClient()
    # Mocking async run synchronously
    import asyncio

    j_res = asyncio.run(fake.judge(pkg))

    h_ann = HumanAnnotation(
        annotator_id="ann-01",
        package_id=pkg.package_id,
        criterion_scores={c.value: 2 for c in JudgeCriterion},
    )

    rec = CalibrationRecord(
        evidence_package=pkg,
        judge_result=j_res,
        human_annotation=h_ann,
    )

    report = compute_calibration_report([rec])
    assert report.n_records == 1
    assert (
        report.validation_status
        == JudgeValidationStatus.ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING
    )
    assert "pending" in report.calibration_note.lower()

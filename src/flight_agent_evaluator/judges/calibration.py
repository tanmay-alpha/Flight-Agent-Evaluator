"""Calibration helpers for the judge system.

This module provides:
- HumanAnnotation: one annotator's scores for one evidence package.
- CalibrationRecord: a labelled (evidence_package, judge_result, human_annotation) triple.
- CalibrationReport: agreement metrics between judge and human labels, plus a
  ``CalibrationStatus`` computed from those metrics against the policy thresholds.

No real human annotations exist in this repository yet, so no calibration has been run.

To calibrate a judge:
1. Generate an annotation bundle with :mod:`flight_agent_evaluator.annotation`.
2. Collect real annotations from qualified annotators.
3. Build ``HumanAnnotation`` objects from the collected scores and pair each with the
   judge result for the same evidence package as a ``CalibrationRecord``.
4. Run ``compute_calibration_report()`` on those records.
5. Only if the status is ``MEETS_THRESHOLD`` and a human has confirmed the annotations are
   real may ``JudgeValidationStatus.HUMAN_CALIBRATED`` be set. The report never sets it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
    JudgeEvidencePackage,
    JudgeMode,
    JudgeResult,
    JudgeScore,
)
from flight_agent_evaluator.judges.metrics import AgreementReport


@dataclass
class HumanAnnotation:
    """A single human annotation for one evidence package.

    Annotators should not be shown the judge's scores or other annotator
    scores until after their annotation is submitted.
    """

    annotator_id: str
    """Pseudonymous annotator identifier."""

    package_id: str
    """Evidence package identifier."""

    criterion_scores: dict[str, JudgeScore]
    """Annotator's scores, keyed by criterion value (string)."""

    rationale: dict[str, str] = field(default_factory=dict)
    """Optional short rationale per criterion."""

    annotated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def score_for(self, criterion: JudgeCriterion) -> JudgeScore | None:
        """Return the score for a criterion, or None if not annotated."""
        value = self.criterion_scores.get(criterion.value)
        return value


@dataclass
class CalibrationRecord:
    """A triple of evidence package, judge result, and human annotation."""

    evidence_package: JudgeEvidencePackage
    judge_result: JudgeResult
    human_annotation: HumanAnnotation


class CalibrationStatus(StrEnum):
    """Outcome of comparing judge/human agreement with the calibration thresholds."""

    INSUFFICIENT_DATA = "insufficient_data"
    """No paired scores, a criterion without paired scores, or an undefined kappa."""

    BELOW_THRESHOLD = "below_threshold"
    """At least one criterion, or the overall agreement, misses a threshold."""

    MEETS_THRESHOLD = "meets_threshold"
    """Overall and every criterion meet both thresholds."""


@dataclass
class CalibrationReport:
    """Agreement report between judge and human annotations."""

    calibration_id: str
    n_records: int
    per_criterion: dict[str, dict[str, float | int | None]]
    overall: dict[str, float | int | None]
    status: CalibrationStatus
    status_reasons: list[str]
    """Why the status is not ``MEETS_THRESHOLD``; empty when it is."""
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    calibration_note: str = (
        "Status is computed only from the agreement between the supplied judge results and "
        "human annotations. MEETS_THRESHOLD does not establish that the annotations are real; "
        "a human must confirm their provenance before the judge is marked HUMAN_CALIBRATED."
    )


# ---------------------------------------------------------------------------
# Calibration thresholds (policy-v1)
# ---------------------------------------------------------------------------

# Minimum acceptable agreement to claim "human calibrated" status.
# These are intentionally conservative and must be met overall and on every criterion.
MIN_ACCEPTABLE_KAPPA = 0.4  # Moderate agreement (Landis & Koch)
MIN_ACCEPTABLE_ADJACENT_AGREEMENT = 0.75  # 75% of scores within ±1


def _paired_scores(
    records: list[CalibrationRecord], criteria: list[JudgeCriterion]
) -> tuple[list[int], list[int]]:
    judge_scores: list[int] = []
    human_scores: list[int] = []
    for criterion in criteria:
        for rec in records:
            j_score = rec.judge_result.criterion_score(criterion)
            h_score = rec.human_annotation.score_for(criterion)
            if j_score is not None and h_score is not None:
                judge_scores.append(int(j_score))
                human_scores.append(int(h_score))
    return judge_scores, human_scores


def _threshold_issue(scope: str, report: AgreementReport) -> tuple[CalibrationStatus, str] | None:
    if math.isnan(report.kappa):
        return (
            CalibrationStatus.INSUFFICIENT_DATA,
            f"{scope}: weighted kappa undefined (no score variance)",
        )
    if report.kappa < MIN_ACCEPTABLE_KAPPA:
        return (
            CalibrationStatus.BELOW_THRESHOLD,
            f"{scope}: weighted kappa {report.kappa:.4f} < {MIN_ACCEPTABLE_KAPPA}",
        )
    if report.adjacent_agreement < MIN_ACCEPTABLE_ADJACENT_AGREEMENT:
        return (
            CalibrationStatus.BELOW_THRESHOLD,
            f"{scope}: adjacent agreement {report.adjacent_agreement:.4f} "
            f"< {MIN_ACCEPTABLE_ADJACENT_AGREEMENT}",
        )
    return None


def compute_calibration_report(
    records: list[CalibrationRecord],
    calibration_id: str = "pending",
) -> CalibrationReport:
    """Compute calibration metrics between judge scores and human annotations.

    Args:
        records: List of (package, judge_result, human_annotation) triples.
        calibration_id: Unique identifier for this calibration run.

    Returns:
        A CalibrationReport with per-criterion and overall metrics and a status:
        ``BELOW_THRESHOLD`` if any measured agreement misses a threshold, otherwise
        ``INSUFFICIENT_DATA`` if anything could not be measured, otherwise
        ``MEETS_THRESHOLD``.

    Raises:
        ValueError: If any judge result came from the fake judge; agreement with
            placeholder scores says nothing about a judge.
    """
    fake_ids = [rec.evidence_package.package_id for rec in records if rec.judge_result.mode is JudgeMode.FAKE]
    if fake_ids:
        raise ValueError(
            f"Calibration requires real judge results; fake-mode results for packages {fake_ids}."
        )

    issues: list[tuple[CalibrationStatus, str]] = []
    per_criterion: dict[str, dict[str, float | int | None]] = {}
    for criterion in JudgeCriterion:
        judge_scores, human_scores = _paired_scores(records, [criterion])
        if not judge_scores:
            issues.append(
                (CalibrationStatus.INSUFFICIENT_DATA, f"{criterion.value}: no paired scores")
            )
            continue
        report = AgreementReport(judge_scores, human_scores)
        per_criterion[criterion.value] = report.to_dict()
        issue = _threshold_issue(criterion.value, report)
        if issue is not None:
            issues.append(issue)

    all_judge, all_human = _paired_scores(records, list(JudgeCriterion))
    overall: dict[str, float | int | None] = {}
    if all_judge:
        overall_report = AgreementReport(all_judge, all_human)
        overall = overall_report.to_dict()
        issue = _threshold_issue("overall", overall_report)
        if issue is not None:
            issues.append(issue)
    else:
        issues.append((CalibrationStatus.INSUFFICIENT_DATA, "overall: no paired scores"))

    statuses = {status for status, _ in issues}
    if CalibrationStatus.BELOW_THRESHOLD in statuses:
        status = CalibrationStatus.BELOW_THRESHOLD
    elif CalibrationStatus.INSUFFICIENT_DATA in statuses:
        status = CalibrationStatus.INSUFFICIENT_DATA
    else:
        status = CalibrationStatus.MEETS_THRESHOLD

    return CalibrationReport(
        calibration_id=calibration_id,
        n_records=len(records),
        per_criterion=per_criterion,
        overall=overall,
        status=status,
        status_reasons=[reason for _, reason in issues],
    )

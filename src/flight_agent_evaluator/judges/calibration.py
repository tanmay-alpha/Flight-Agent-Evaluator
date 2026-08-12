"""Calibration helpers for the judge system.

Calibration status: engineering complete; human calibration pending.

This module provides:
- CalibrationRecord: A labelled (evidence_package, judge_result, human_annotation) triple.
- CalibrationDataset: A collection of CalibrationRecords.
- CalibrationReport: Agreement metrics between judge and human labels.

The module is intentionally designed so that validation cannot be performed
without real human labels.  Status is tracked as an honest pending state.

To add real human annotations:
1. Generate an annotation bundle using the annotation package.
2. Collect real annotations from qualified annotators.
3. Import annotations using annotation.importer.
4. Run calibration.compute_calibration_report() with the imported annotations.
5. Update JudgeValidationStatus to HUMAN_CALIBRATED if metrics pass thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
    JudgeEvidencePackage,
    JudgeResult,
    JudgeScore,
    JudgeValidationStatus,
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


@dataclass
class CalibrationReport:
    """Agreement report between judge and human annotations."""

    calibration_id: str
    n_records: int
    per_criterion: dict[str, dict[str, float | int | None]]
    overall: dict[str, float | int | None]
    validation_status: JudgeValidationStatus
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    calibration_note: str = (
        "Human calibration pending. "
        "Scores below were computed from replay/fake judges, not human annotations. "
        "Do not cite as evidence of judge quality until real annotations are collected."
    )


# ---------------------------------------------------------------------------
# Calibration thresholds (policy-v1)
# ---------------------------------------------------------------------------

# Minimum acceptable agreement to claim "human calibrated" status.
# These are intentionally conservative and must be met on all criteria.
MIN_ACCEPTABLE_KAPPA = 0.4  # Moderate agreement (Landis & Koch)
MIN_ACCEPTABLE_ADJACENT_AGREEMENT = 0.75  # 75% of scores within ±1


def compute_calibration_report(
    records: list[CalibrationRecord],
    calibration_id: str = "pending",
) -> CalibrationReport:
    """Compute calibration metrics between judge scores and human annotations.

    Args:
        records: List of (package, judge_result, human_annotation) triples.
        calibration_id: Unique identifier for this calibration run.

    Returns:
        A CalibrationReport with per-criterion and overall metrics.
        Validation status reflects whether human labels are real.
    """
    if not records:
        return CalibrationReport(
            calibration_id=calibration_id,
            n_records=0,
            per_criterion={},
            overall={},
            validation_status=JudgeValidationStatus.ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING,
        )

    per_criterion: dict[str, dict[str, float | int | None]] = {}

    for criterion in JudgeCriterion:
        judge_scores: list[int] = []
        human_scores: list[int] = []
        for rec in records:
            j_score = rec.judge_result.criterion_score(criterion)
            h_score = rec.human_annotation.score_for(criterion)
            if j_score is not None and h_score is not None:
                judge_scores.append(int(j_score))
                human_scores.append(int(h_score))
        if judge_scores:
            report = AgreementReport(judge_scores, human_scores)
            per_criterion[criterion.value] = report.to_dict()

    # Overall metrics (aggregate across criteria)
    all_judge: list[int] = []
    all_human: list[int] = []
    for criterion in JudgeCriterion:
        for rec in records:
            j_score = rec.judge_result.criterion_score(criterion)
            h_score = rec.human_annotation.score_for(criterion)
            if j_score is not None and h_score is not None:
                all_judge.append(int(j_score))
                all_human.append(int(h_score))

    if all_judge:
        overall_report = AgreementReport(all_judge, all_human)
        overall = overall_report.to_dict()
    else:
        overall = {}

    # Determine validation status (conservative)
    status = JudgeValidationStatus.ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING
    if all_judge:
        overall_report = AgreementReport(all_judge, all_human)
        kappa = overall_report.kappa
        adjacent = overall_report.adjacent_agreement
        import math

        if (
            not math.isnan(kappa)
            and kappa >= MIN_ACCEPTABLE_KAPPA
            and adjacent >= MIN_ACCEPTABLE_ADJACENT_AGREEMENT
        ):
            # Still only PENDING — human confirmation required to flip to CALIBRATED.
            # The status is set by a human decision, not automatically.
            status = JudgeValidationStatus.ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING

    return CalibrationReport(
        calibration_id=calibration_id,
        n_records=len(records),
        per_criterion=per_criterion,
        overall=overall,
        validation_status=status,
    )

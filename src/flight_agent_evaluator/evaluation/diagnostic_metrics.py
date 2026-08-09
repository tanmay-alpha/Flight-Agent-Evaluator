"""Diagnostic consistency metrics for the Stage 3 challenge set.

Gate 13 of the Stage 3 diagnostic validity specification.

These metrics measure the diagnostic engine's consistency against synthetic
labels that are known by construction (from controlled perturbations).

IMPORTANT: These metrics measure synthetic consistency, NOT human-validation
accuracy.  They cannot substitute for human-labelled validation data.
Report them separately and document this distinction clearly.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from flight_agent_evaluator.evaluation.failure_codes import (
    FailureCode,
    FailureOrigin,
    FailureSeverity,
)


@dataclasses.dataclass(frozen=True)
class ChallengeLabel:
    """Expected label for a single challenge case (known by construction)."""

    case_id: str
    primary_code: FailureCode
    secondary_codes: tuple[FailureCode, ...] = ()
    origin: FailureOrigin = FailureOrigin.AGENT
    severity: FailureSeverity = FailureSeverity.HIGH
    critical_step_sequence: int | None = None
    """Expected journal sequence of the critical failure step, or None."""


@dataclasses.dataclass(frozen=True)
class ChallengeResult:
    """Actual diagnostic output for a single challenge case."""

    case_id: str
    predicted_primary_code: FailureCode | None
    predicted_secondary_codes: tuple[FailureCode, ...]
    predicted_origin: FailureOrigin | None
    predicted_severity: FailureSeverity | None
    critical_step_sequence: int | None


@dataclasses.dataclass(frozen=True)
class DiagnosticMetrics:
    """Diagnostic consistency metrics against synthetic challenge labels.

    All metrics are in [0.0, 1.0] except where noted.

    Terminology
    -----------
    - primary_label_accuracy: fraction of cases where predicted primary code == expected primary code.
    - multi_label_*: multi-label metrics treating all codes (primary + secondary) as a label set.
    - critical_step_exact_accuracy: fraction of cases where predicted critical step sequence == expected.
    - critical_step_within_one_action_accuracy: fraction of cases where |predicted - expected| <= 1.
    - origin_accuracy: fraction of cases where predicted origin == expected origin.
    - severity_accuracy: fraction of cases where predicted severity == expected severity.
    - unclassified_rate: fraction of cases with UNKNOWN.UNCLASSIFIED as the primary code.
    """

    n_cases: int

    primary_label_accuracy: float
    """Exact match on primary failure code."""

    multi_label_micro_precision: float
    """TP / (TP + FP) across all label assignments (micro)."""

    multi_label_micro_recall: float
    """TP / (TP + FN) across all label assignments (micro)."""

    multi_label_micro_f1: float
    """Harmonic mean of micro precision and recall."""

    multi_label_macro_f1: float
    """Average per-class F1 (macro), where classes are unique failure codes in ground truth."""

    critical_step_exact_accuracy: float
    """Exact match on critical-step journal sequence number."""

    critical_step_within_one_action_accuracy: float
    """Fraction of cases where |predicted_seq - expected_seq| <= 1 (or both None)."""

    origin_accuracy: float
    """Exact match on failure origin."""

    severity_accuracy: float
    """Exact match on failure severity."""

    unclassified_rate: float
    """Fraction of cases where primary code == UNKNOWN.UNCLASSIFIED."""


def compute_diagnostic_metrics(
    labels: Sequence[ChallengeLabel],
    results: Sequence[ChallengeResult],
) -> DiagnosticMetrics:
    """Compute diagnostic metrics for a set of challenge cases.

    Parameters
    ----------
    labels:
        Ground-truth labels (known by construction, not human-labelled).
    results:
        Actual diagnostic outputs for the same cases.

    Both sequences must have the same length and matching case IDs.
    """
    if not labels:
        return DiagnosticMetrics(
            n_cases=0,
            primary_label_accuracy=0.0,
            multi_label_micro_precision=0.0,
            multi_label_micro_recall=0.0,
            multi_label_micro_f1=0.0,
            multi_label_macro_f1=0.0,
            critical_step_exact_accuracy=0.0,
            critical_step_within_one_action_accuracy=0.0,
            origin_accuracy=0.0,
            severity_accuracy=0.0,
            unclassified_rate=0.0,
        )

    n = len(labels)

    # Index results by case_id
    result_map: dict[str, ChallengeResult] = {r.case_id: r for r in results}

    # -----------------------------------------------------------------
    # Primary label accuracy
    # -----------------------------------------------------------------
    primary_correct = 0
    for lbl in labels:
        res = result_map.get(lbl.case_id)
        if res is not None and res.predicted_primary_code == lbl.primary_code:
            primary_correct += 1
    primary_label_accuracy = primary_correct / n

    # -----------------------------------------------------------------
    # Multi-label metrics (treat all codes as a set per case)
    # -----------------------------------------------------------------
    total_tp = 0
    total_fp = 0
    total_fn = 0

    # For macro F1: per-class TP/FP/FN
    class_tp: dict[FailureCode, int] = {}
    class_fp: dict[FailureCode, int] = {}
    class_fn: dict[FailureCode, int] = {}

    for lbl in labels:
        res = result_map.get(lbl.case_id)
        gt_set: frozenset[FailureCode] = frozenset({lbl.primary_code} | set(lbl.secondary_codes))
        pred_set: frozenset[FailureCode]
        if res is None:
            pred_set = frozenset()
        else:
            pred_codes = {res.predicted_primary_code} if res.predicted_primary_code else set()
            pred_codes |= set(res.predicted_secondary_codes)
            pred_set = frozenset(pred_codes)

        tp = len(gt_set & pred_set)
        fp = len(pred_set - gt_set)
        fn = len(gt_set - pred_set)

        total_tp += tp
        total_fp += fp
        total_fn += fn

        for code in gt_set:
            class_tp.setdefault(code, 0)
            class_fp.setdefault(code, 0)
            class_fn.setdefault(code, 0)
            if code in pred_set:
                class_tp[code] += 1
            else:
                class_fn[code] += 1

        for code in pred_set - gt_set:
            class_fp.setdefault(code, 0)
            class_fp[code] += 1

    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall) > 0
        else 0.0
    )

    # Macro F1: average over all unique ground-truth classes
    all_classes = set(class_tp.keys())
    per_class_f1: list[float] = []
    for code in all_classes:
        tp_c = class_tp.get(code, 0)
        fp_c = class_fp.get(code, 0)
        fn_c = class_fn.get(code, 0)
        p = tp_c / (tp_c + fp_c) if (tp_c + fp_c) > 0 else 0.0
        r = tp_c / (tp_c + fn_c) if (tp_c + fn_c) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        per_class_f1.append(f1)
    macro_f1 = sum(per_class_f1) / len(per_class_f1) if per_class_f1 else 0.0

    # -----------------------------------------------------------------
    # Critical step accuracy
    # -----------------------------------------------------------------
    cs_exact = 0
    cs_within_one = 0
    cs_total = 0

    for lbl in labels:
        if lbl.critical_step_sequence is None:
            continue
        cs_total += 1
        res = result_map.get(lbl.case_id)
        pred_seq = res.critical_step_sequence if res else None
        if pred_seq == lbl.critical_step_sequence:
            cs_exact += 1
            cs_within_one += 1
        elif pred_seq is not None and abs(pred_seq - lbl.critical_step_sequence) <= 1:
            cs_within_one += 1

    cs_exact_acc = cs_exact / cs_total if cs_total > 0 else 0.0
    cs_within_one_acc = cs_within_one / cs_total if cs_total > 0 else 0.0

    # -----------------------------------------------------------------
    # Origin and severity accuracy
    # -----------------------------------------------------------------
    origin_correct = 0
    sev_correct = 0

    for lbl in labels:
        res = result_map.get(lbl.case_id)
        if res is not None and res.predicted_origin == lbl.origin:
            origin_correct += 1
        if res is not None and res.predicted_severity == lbl.severity:
            sev_correct += 1

    origin_accuracy = origin_correct / n
    severity_accuracy = sev_correct / n

    # -----------------------------------------------------------------
    # Unclassified rate
    # -----------------------------------------------------------------
    unclassified = sum(
        1
        for lbl in labels
        if (
            (res := result_map.get(lbl.case_id)) is not None
            and res.predicted_primary_code == FailureCode.UNKNOWN__UNCLASSIFIED
        )
    )
    unclassified_rate = unclassified / n

    return DiagnosticMetrics(
        n_cases=n,
        primary_label_accuracy=primary_label_accuracy,
        multi_label_micro_precision=micro_precision,
        multi_label_micro_recall=micro_recall,
        multi_label_micro_f1=micro_f1,
        multi_label_macro_f1=macro_f1,
        critical_step_exact_accuracy=cs_exact_acc,
        critical_step_within_one_action_accuracy=cs_within_one_acc,
        origin_accuracy=origin_accuracy,
        severity_accuracy=severity_accuracy,
        unclassified_rate=unclassified_rate,
    )

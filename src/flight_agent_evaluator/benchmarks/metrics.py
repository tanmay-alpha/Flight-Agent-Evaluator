"""Metrics calculation for benchmark runs and failure classification accuracy."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flight_agent_evaluator.benchmarks.results import BenchmarkCaseResult


def compute_pass_rate(results: Sequence[BenchmarkCaseResult]) -> float:
    """Compute pass rate ratio (0.0 to 1.0) across case benchmark results."""
    if not results:
        return 0.0
    passed_count = sum(1 for r in results if r.task_success)
    return round(passed_count / len(results), 4)


def compute_average_score(results: Sequence[BenchmarkCaseResult]) -> float:
    """Compute mean overall score across case benchmark results."""
    if not results:
        return 0.0
    total_score = sum(r.overall_score for r in results)
    return round(total_score / len(results), 4)


def compute_macro_f1(
    ground_truth_failures: Sequence[set[str]],
    predicted_failures: Sequence[set[str]],
) -> float:
    """Compute macro-averaged F1 score for failure classification accuracy."""
    if not ground_truth_failures or len(ground_truth_failures) != len(predicted_failures):
        return 0.0

    all_codes = set().union(*ground_truth_failures, *predicted_failures)
    if not all_codes:
        return 1.0  # Perfect agreement when no failure codes exist

    f1_scores: list[float] = []
    for code in sorted(all_codes):
        tp = sum(
            1
            for gt, pred in zip(ground_truth_failures, predicted_failures, strict=True)
            if code in gt and code in pred
        )
        fp = sum(
            1
            for gt, pred in zip(ground_truth_failures, predicted_failures, strict=True)
            if code not in gt and code in pred
        )
        fn = sum(
            1
            for gt, pred in zip(ground_truth_failures, predicted_failures, strict=True)
            if code in gt and code not in pred
        )

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        f1_scores.append(f1)

    return round(sum(f1_scores) / len(f1_scores), 4)

"""Markdown rendering for evaluator validation reports."""

from __future__ import annotations

from flight_agent_evaluator.evaluation.validation.harness import EvaluatorValidationReport
from flight_agent_evaluator.evaluation.validation.metrics import ConfusionMatrix, RateEstimate

_LABEL_NOTE = (
    "Labels are synthetic-by-construction: each case is the scenario's authored golden "
    "trajectory with one deterministic perturbation, labelled by what the perturbation "
    "does. They are not human annotations. Results measure whether the evaluator "
    "detects these specific injected defects on this benchmark's scenarios; they do not "
    "estimate accuracy on real agent trajectories, and clean controls assume the authored "
    "golden trajectories are correct."
)


def _estimate(estimate: RateEstimate, count: int | None = None) -> str:
    interval = (
        "undefined"
        if estimate.wilson95 is None
        else f"[{estimate.wilson95[0]:.3f}, {estimate.wilson95[1]:.3f}]"
    )
    value = (
        str(count)
        if count is not None
        else "insufficient n"
        if estimate.rate is None
        else f"{estimate.rate:.3f}"
    )
    status = "; insufficient n" if estimate.status == "insufficient_n" else ""
    return f"{value} (n={estimate.n}; Wilson95 {interval}{status})"


def _matrix_row(name: str, matrix: ConfusionMatrix) -> str:
    statistics = matrix.statistics
    cells = [
        _estimate(statistics[field], getattr(matrix, field))
        for field in ("true_positive", "false_positive", "false_negative", "true_negative")
    ]
    cells.extend(
        _estimate(statistics[field])
        for field in ("precision", "recall", "false_positive_rate", "false_negative_rate")
    )
    return f"| {name} | " + " | ".join(cells) + " |"


def render_markdown(report: EvaluatorValidationReport) -> str:
    """Render ``report`` as deterministic Markdown."""
    lines: list[str] = [
        "# Evaluator validation report",
        "",
        f"- Benchmark: `{report.benchmark_id}` v{report.benchmark_version}",
        f"- Manifest digest: `{report.manifest_digest}`",
        f"- Report schema: `{report.schema_version}`",
        f"- Suite: `{report.suite}`",
        f"- Detector source SHA-256: `{report.detector_source_digest}`",
        f"- Suite manifest SHA-256: `{report.suite_manifest_digest or 'historical-v1'}`",
        f"- Prior dev report digest: `{report.dev_report_digest or 'not applicable'}`",
        f"- Label provenance: `{report.label_provenance}`",
        f"- Cases run: {len(report.cases)}; scored: {len(report.cases) - len(report.excluded)}; "
        f"operator/scenario pairs skipped: {len(report.skipped)}",
        "",
        f"> {_LABEL_NOTE}",
        "",
        "> Every cell includes its denominator n and Wilson 95% interval. Point rates "
        "with n < 10 are withheld as insufficient n. Intervals describe synthetic "
        "binomial cells, not generalisation to real agents; cases within a scenario "
        "are correlated and are not independent scenario samples.",
        "",
        "## Operators",
        "",
        "| Operator | Label policy |",
        "| --- | --- |",
    ]
    lines.extend(f"| `{spec.operator.value}` | {spec.label_policy} |" for spec in report.operators)

    header = [
        "| Operator | TP | FP | FN | TN | Precision | Recall | FP rate | FN rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for summary in report.dimensions:
        lines.extend(["", f"## Dimension: `{summary.dimension.value}`", "", *header])
        lines.extend(
            _matrix_row(f"`{operator}`", matrix) for operator, matrix in summary.by_operator.items()
        )
        lines.append(_matrix_row("**overall**", summary.overall))

    lines.extend(["", f"## Misclassified ({len(report.misclassified)})", ""])
    if report.misclassified:
        lines.extend(
            [
                "| Scenario | Operator | Dimension | Kind | task_success | safety_pass | "
                "efficiency | Failure codes | Case ID | Expected | Observed |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {item.scenario_id} | `{item.operator.value}` | `{item.dimension.value}` | "
            f"{item.kind} | {item.observation.task_success} | {item.observation.safety_pass} | "
            f"{item.observation.efficiency_score:.3f} | "
            f"{', '.join(item.observation.failure_codes) or '-'} | "
            f"{item.case_id or item.scenario_id} | {item.expected} | {item.observed} |"
            for item in report.misclassified
        )
    else:
        lines.append("None.")

    if report.failure_code_metrics:
        lines.extend(["", "## Required failure-code detection", "", *header])
        lines.extend(
            _matrix_row(f"`{code}`", matrix) for code, matrix in report.failure_code_metrics.items()
        )
        lines.extend(
            [
                "",
                "Only explicitly asserted codes enter these positive-only cells. In particular, "
                "FALSE_SUCCESS does not satisfy an injection-attribution label.",
            ]
        )
    lines.extend(["", f"## Missing required codes ({len(report.code_misclassified)})", ""])
    if report.code_misclassified:
        lines.extend(
            [
                "| Case ID | Required codes missed | Observed failure codes |",
                "| --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {case.case_id} | {', '.join(case.missing_expected_codes)} | "
            f"{', '.join(case.observation.failure_codes) or '-'} |"
            for case in report.code_misclassified
        )
    else:
        lines.append("None.")

    if report.excluded:
        lines.extend(
            [
                "",
                "## Excluded (scripted agent did not complete)",
                "",
                *(f"- {case_id}" for case_id in report.excluded),
            ]
        )

    lines.extend(
        [
            "",
            "## Skipped operator applications",
            "",
            "| Scenario | Operator | Reason |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {item.scenario_id} | `{item.operator.value}` | {item.reason} |"
        for item in report.skipped
    )
    return "\n".join(lines) + "\n"

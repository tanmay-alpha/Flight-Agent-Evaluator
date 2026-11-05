"""Markdown rendering for evaluator validation reports."""

from __future__ import annotations

from flight_agent_evaluator.evaluation.validation.harness import EvaluatorValidationReport
from flight_agent_evaluator.evaluation.validation.metrics import ConfusionMatrix

_LABEL_NOTE = (
    "Labels are synthetic-by-construction: each case is the scenario's authored golden "
    "trajectory with one deterministic perturbation, labelled by what the perturbation "
    "does. They are not human annotations. Results measure whether the evaluator "
    "detects these specific injected defects on this benchmark's scenarios; they do not "
    "estimate accuracy on real agent trajectories, and clean controls assume the authored "
    "golden trajectories are correct."
)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _matrix_row(name: str, matrix: ConfusionMatrix) -> str:
    return (
        f"| {name} | {matrix.true_positive} | {matrix.false_positive} | "
        f"{matrix.false_negative} | {matrix.true_negative} | {_fmt(matrix.precision)} | "
        f"{_fmt(matrix.recall)} | {_fmt(matrix.false_positive_rate)} | "
        f"{_fmt(matrix.false_negative_rate)} |"
    )


def render_markdown(report: EvaluatorValidationReport) -> str:
    """Render ``report`` as deterministic Markdown."""
    lines: list[str] = [
        "# Evaluator validation report",
        "",
        f"- Benchmark: `{report.benchmark_id}` v{report.benchmark_version}",
        f"- Manifest digest: `{report.manifest_digest}`",
        f"- Report schema: `{report.schema_version}`",
        f"- Label provenance: `{report.label_provenance}`",
        f"- Cases run: {len(report.cases)}; scored: {len(report.cases) - len(report.excluded)}; "
        f"operator/scenario pairs skipped: {len(report.skipped)}",
        "",
        f"> {_LABEL_NOTE}",
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
                "efficiency | Failure codes |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {item.scenario_id} | `{item.operator.value}` | `{item.dimension.value}` | "
            f"{item.kind} | {item.observation.task_success} | {item.observation.safety_pass} | "
            f"{item.observation.efficiency_score:.3f} | "
            f"{', '.join(item.observation.failure_codes) or '-'} |"
            for item in report.misclassified
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

"""Report generator for multi-model benchmark runs and ablation studies."""

from __future__ import annotations

from flight_agent_evaluator.benchmarks.contracts import (
    AblationComparisonReport,
    BenchmarkRunSummary,
)


def generate_benchmark_report(summary: BenchmarkRunSummary) -> str:
    """Generate markdown leaderboard and summary report for a benchmark run."""
    lines: list[str] = [
        f"# Benchmark Run Report: `{summary.run_id}`",
        "",
        f"**Evaluated At**: {summary.evaluated_at.isoformat()}",
        f"**Scenarios Count**: {summary.scenarios_count}",
        f"**Total Runs**: {summary.total_runs}",
        f"**Ablation Config**: `{summary.ablation_config.name}` ({summary.ablation_config.description})",
        "",
        "## Model Leaderboard",
        "",
        "| Model Name | Pass Rate (%) | Average Score | Total Runs |",
        "|------------|---------------|---------------|------------|",
    ]

    for model in summary.models_evaluated:
        pass_rate = summary.model_pass_rates.get(model, 0.0) * 100.0
        avg_score = summary.model_average_scores.get(model, 0.0)
        m_runs = sum(1 for r in summary.results if r.model_name == model)
        lines.append(f"| `{model}` | {pass_rate:.1f}% | {avg_score:.3f} | {m_runs} |")

    lines.extend(
        [
            "",
            "## Key Findings",
            "",
            f"- Evaluated {len(summary.models_evaluated)} models across {summary.scenarios_count} scenarios.",
            f"- Top performing model: `{summary.models_evaluated[0] if summary.models_evaluated else 'N/A'}`.",
        ]
    )

    return "\n".join(lines)


def generate_ablation_report(report: AblationComparisonReport) -> str:
    """Generate markdown report for an ablation study."""
    lines: list[str] = [
        f"# Evaluator Ablation Study Report: `{report.report_id}`",
        "",
        f"**Generated At**: {report.generated_at.isoformat()}",
        f"**Evaluator Value-Add Score**: **{report.evaluator_value_add_score:.1f}%**",
        "",
        "## Ablation Performance Comparison",
        "",
        "| Ablation Setting | Pass Rate (%) | Failure Macro F1 |",
        "|------------------|---------------|------------------|",
    ]

    for setting, pass_rate in report.ablated_pass_rates.items():
        f1 = report.failure_classification_macro_f1.get(setting, 0.0)
        lines.append(f"| `{setting}` | {pass_rate * 100.0:.1f}% | {f1:.3f} |")

    lines.extend(
        [
            "",
            "## Key Findings",
            "",
        ]
    )
    lines.extend(f"- {finding}" for finding in report.key_findings)
    return "\n".join(lines)

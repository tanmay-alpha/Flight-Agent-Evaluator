"""Report generator for canonical benchmark runs and evaluation metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flight_agent_evaluator.benchmarks.results import BenchmarkRunArtifact


def generate_benchmark_report(artifact: BenchmarkRunArtifact) -> str:
    """Generate markdown leaderboard and summary report for a canonical benchmark run."""
    metrics = artifact.metrics
    lines: list[str] = [
        f"# Benchmark Run Report: `{artifact.run_semantic_id}`",
        "",
        f"**Benchmark ID**: `{artifact.benchmark_id}` (v{artifact.benchmark_version})",
        f"**Manifest Digest**: `{artifact.manifest_digest}`",
        f"**Scenario Count**: {artifact.scenario_count}",
        f"**Total Executions**: {artifact.total_runs}",
        f"**Task Success Rate**: {metrics.task_success_rate * 100:.1f}%",
        f"**Safety Pass Rate**: {metrics.safety_pass_rate * 100:.1f}%",
        f"**Average Overall Score**: {metrics.average_overall_score:.3f} / 1.000",
        "",
        "## Agent Leaderboard",
        "",
        "| Agent ID | Pass Rate (%) | Average Score | Total Runs |",
        "|----------|---------------|---------------|------------|",
    ]

    for agent_id in artifact.executed_agents:
        pass_rate = metrics.agent_pass_rates.get(agent_id, 0.0) * 100.0
        avg_score = metrics.agent_average_scores.get(agent_id, 0.0)
        a_runs = sum(1 for r in artifact.case_results if r.agent_id == agent_id)
        lines.append(f"| `{agent_id}` | {pass_rate:.1f}% | {avg_score:.3f} | {a_runs} |")

    return "\n".join(lines)

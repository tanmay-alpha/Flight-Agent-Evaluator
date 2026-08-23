"""Authoritative benchmark results, deterministic digests, and atomic artifact persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.contracts.base import ContractModel


class BenchmarkCaseResult(ContractModel):
    """Evaluation result for a single agent policy on a single verified benchmark case."""

    benchmark_id: str
    benchmark_version: str
    manifest_digest: str | None = None

    scenario_id: str
    scenario_version: int | str
    scenario_resource_digest: str
    expectation_resource_digest: str

    agent_id: str
    agent_version: str = "1.0.0"
    agent_configuration_digest: str | None = None

    seed: int = 42
    repetition_index: int = 0

    task_success: bool
    safety_pass: bool
    evaluator_status: str = "passed"

    overall_score: float = Field(..., ge=0.0, le=1.0)
    score_vector: dict[str, float] = Field(default_factory=dict)
    failure_codes: list[str] = Field(default_factory=list)

    run_id: str
    journal_digest: str | None = None
    logical_duration_ms: float = 0.0
    wall_time_ms: float = 0.0

    semantic_result_digest: str | None = None

    def compute_semantic_result_digest(self) -> str:
        """Compute deterministic SHA-256 digest of semantic execution outcome (excluding wall-clock timing)."""
        data: dict[str, Any] = {
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "manifest_digest": self.manifest_digest,
            "scenario_id": self.scenario_id,
            "scenario_version": str(self.scenario_version),
            "scenario_resource_digest": self.scenario_resource_digest,
            "expectation_resource_digest": self.expectation_resource_digest,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "agent_configuration_digest": self.agent_configuration_digest,
            "seed": self.seed,
            "repetition_index": self.repetition_index,
            "task_success": self.task_success,
            "safety_pass": self.safety_pass,
            "evaluator_status": self.evaluator_status,
            "overall_score": round(self.overall_score, 4),
            "score_vector": {k: round(v, 4) for k, v in sorted(self.score_vector.items())},
            "failure_codes": sorted(self.failure_codes),
            "journal_digest": self.journal_digest,
        }
        return canonical_hash(data)


class BenchmarkAggregateMetrics(ContractModel):
    """Aggregate statistics across executed benchmark cases."""

    total_cases: int
    total_runs: int
    task_success_rate: float = Field(..., ge=0.0, le=1.0)
    safety_pass_rate: float = Field(..., ge=0.0, le=1.0)
    evaluator_error_rate: float = Field(..., ge=0.0, le=1.0)
    average_overall_score: float = Field(..., ge=0.0, le=1.0)
    agent_pass_rates: dict[str, float] = Field(default_factory=dict)
    agent_average_scores: dict[str, float] = Field(default_factory=dict)


class BenchmarkRunArtifact(ContractModel):
    """Complete, self-contained artifact recording an authoritative benchmark execution run."""

    run_semantic_id: str
    benchmark_id: str
    benchmark_version: str
    manifest_digest: str
    package_version: str = "0.2.0"
    source_commit_sha: str | None = None

    environment_version: str = "1.0.0"
    evaluator_version: str = "1.0.0"
    taxonomy_version: str = "1.0.0"
    scoring_profile_version: str = "1.0.0"

    selected_scenario_ids: list[str] = Field(default_factory=list)
    executed_agents: list[str] = Field(default_factory=list)
    run_policy: dict[str, Any] = Field(default_factory=dict)

    scenario_count: int
    total_runs: int
    metrics: BenchmarkAggregateMetrics
    case_results: list[BenchmarkCaseResult]
    persisted_at: str | None = None

    def render_markdown_report(self) -> str:
        """Render authoritative markdown report for README.md directly from artifact state."""
        return render_benchmark_report(self)

    def persist_atomic(self, output_dir: Path | str) -> None:
        """Atomically persist run artifacts to disk, including run.json, summary.json, README.md, and cases/*.json."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        cases_dir = out_path / "cases"
        cases_dir.mkdir(parents=True, exist_ok=True)

        def _atomic_write_file(file_path: Path, content: str) -> None:
            tmp_path = file_path.with_suffix(f"{file_path.suffix}.tmp")
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.replace(file_path)

        # 1. Write individual case results
        for res in self.case_results:
            case_file_name = f"{res.scenario_id}__{res.agent_id}__rep{res.repetition_index}.json"
            case_file = cases_dir / case_file_name
            _atomic_write_file(case_file, res.model_dump_json(indent=2))

        # 2. Write summary.json
        summary_file = out_path / "summary.json"
        _atomic_write_file(summary_file, self.metrics.model_dump_json(indent=2))

        # 3. Write run.json
        run_file = out_path / "run.json"
        _atomic_write_file(run_file, self.model_dump_json(indent=2))

        # 4. Write authoritative README.md
        readme_file = out_path / "README.md"
        _atomic_write_file(readme_file, self.render_markdown_report())


def render_benchmark_report(artifact: BenchmarkRunArtifact) -> str:
    """Render authoritative markdown report directly from in-memory BenchmarkRunArtifact."""
    lines: list[str] = [
        f"# Benchmark Run Report: `{artifact.run_semantic_id}`",
        "",
        f"- **Benchmark ID**: `{artifact.benchmark_id}` (v{artifact.benchmark_version})",
        f"- **Package Version**: `{artifact.package_version}`",
    ]
    if artifact.source_commit_sha:
        lines.append(f"- **Source Commit SHA**: `{artifact.source_commit_sha}`")
    lines.extend(
        [
            f"- **Manifest Digest**: `{artifact.manifest_digest}`",
            f"- **Run Semantic ID**: `{artifact.run_semantic_id}`",
            f"- **Scenario Count**: {artifact.scenario_count}",
            f"- **Total Executions**: {artifact.total_runs}",
            f"- **Task Success Rate**: {artifact.metrics.task_success_rate * 100:.1f}%",
            f"- **Safety Pass Rate**: {artifact.metrics.safety_pass_rate * 100:.1f}%",
            f"- **Average Overall Score**: {artifact.metrics.average_overall_score:.3f} / 1.000",
            f"- **Evaluator Error Rate**: {artifact.metrics.evaluator_error_rate * 100:.1f}%",
            "",
            "## Agent Leaderboard",
            "",
            "| Agent ID | Task Success Rate | Safety Pass Rate | Average Overall Score | Total Runs |",
            "|---|---|---|---|---|",
        ]
    )

    for aid in artifact.executed_agents:
        a_cases = [r for r in artifact.case_results if r.agent_id == aid]
        a_runs = len(a_cases)
        if a_runs > 0:
            pass_rate = (sum(1 for r in a_cases if r.task_success) / a_runs) * 100
            safety_rate = (sum(1 for r in a_cases if r.safety_pass) / a_runs) * 100
            avg_score = sum(r.overall_score for r in a_cases) / a_runs
        else:
            pass_rate = 0.0
            safety_rate = 100.0
            avg_score = 0.0
        lines.append(
            f"| `{aid}` | {pass_rate:.1f}% | {safety_rate:.1f}% | {avg_score:.3f} | {a_runs} |"
        )

    lines.extend(
        [
            "",
            "## Limitations & Evaluation Scope",
            "",
            "1. **Simulated Environment**: Scenarios execute in a simulated airline environment with synthetic carrier APIs and controlled fault injection.",
            "2. **Deterministic Baselines**: Baseline policies (`scripted-oracle`, `naive-baseline`, `no-op-baseline`) execute deterministic routines without live LLM calls.",
            "3. **No Live Model in Canonical Baseline**: The canonical benchmark baseline evaluates deterministic reference agents for reproducibility.",
            "4. **Qualitative Judge Calibration**: Qualitative judge rubric human calibration is currently pending.",
            "",
        ]
    )

    return "\n".join(lines)

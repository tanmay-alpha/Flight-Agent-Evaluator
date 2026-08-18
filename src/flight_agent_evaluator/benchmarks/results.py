"""Authoritative benchmark results, deterministic digests, and atomic artifact persistence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import Field

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
        canonical_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


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
    executed_agents: list[str]
    scenario_count: int
    total_runs: int
    metrics: BenchmarkAggregateMetrics
    case_results: list[BenchmarkCaseResult]
    persisted_at: str | None = None

    def persist_atomic(self, output_dir: Path | str) -> None:
        """Atomically persist run artifacts to disk."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        cases_dir = out_path / "cases"
        cases_dir.mkdir(parents=True, exist_ok=True)

        def _atomic_write_json(file_path: Path, content: str) -> None:
            tmp_path = file_path.with_suffix(f"{file_path.suffix}.tmp")
            tmp_path.write_text(content, encoding="utf-8")
            tmp_path.replace(file_path)

        # 1. Write individual case results
        for res in self.case_results:
            case_file_name = f"{res.scenario_id}__{res.agent_id}__rep{res.repetition_index}.json"
            case_file = cases_dir / case_file_name
            _atomic_write_json(case_file, res.model_dump_json(indent=2))

        # 2. Write summary.json
        summary_file = out_path / "summary.json"
        _atomic_write_json(summary_file, self.metrics.model_dump_json(indent=2))

        # 3. Write run.json
        run_file = out_path / "run.json"
        _atomic_write_json(run_file, self.model_dump_json(indent=2))

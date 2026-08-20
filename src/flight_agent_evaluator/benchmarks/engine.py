"""Canonical benchmark engine orchestrating manifest loading, case execution, and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path

from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkManifestLoader,
)
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
    UnknownBenchmarkAgentError,
)
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
    BenchmarkRunArtifact,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner

logger = logging.getLogger(__name__)


class CanonicalBenchmarkEngine:
    """Single authoritative orchestrator for content-addressed benchmark execution."""

    def __init__(
        self,
        resource_root: Path | str | None = None,
        registry: BenchmarkAgentRegistry | None = None,
        loader: BenchmarkManifestLoader | None = None,
        runner: BenchmarkRunner | None = None,
    ) -> None:
        self.loader = loader or BenchmarkManifestLoader(resource_root=resource_root)
        self.registry = registry or BenchmarkAgentRegistry()
        self.runner = runner or BenchmarkRunner()

    def run_benchmark(
        self,
        manifest_path: Path | str = "builtin:benchmark-v1",
        agent_ids: Sequence[str] | None = None,
        output_dir: Path | str | None = None,
        repetitions: int | None = None,
    ) -> BenchmarkRunArtifact:
        """Execute authoritative benchmark run across verified manifest cases and exact agents."""
        manifest, cases = self.loader.load_manifest(manifest_path, verify_resources=True)

        selected_agent_ids = (
            [aid.strip() for aid in agent_ids]
            if agent_ids
            else [ag.agent_id for ag in manifest.agents]
        )
        if not selected_agent_ids:
            raise UnknownBenchmarkAgentError("No benchmark agents specified or found in manifest.")

        # Resolve exact agent policies
        resolved_agents: list[tuple[str, AgentPolicy]] = []
        for aid in selected_agent_ids:
            agent_policy = self.registry.resolve(aid)
            resolved_agents.append((aid, agent_policy))

        rep_count = repetitions if repetitions is not None else manifest.run_policy.repetitions
        case_results: list[BenchmarkCaseResult] = []

        # Execute all cases across agents and repetitions
        for aid, agent in resolved_agents:
            for rep_idx in range(rep_count):
                for case in cases:
                    case_res = asyncio.run(
                        self.runner.run_case(
                            case=case,
                            agent=agent,
                            repetition_index=rep_idx,
                        )
                    )
                    # Bind manifest digest and exact agent ID
                    m_digest = manifest.manifest_digest or manifest.compute_canonical_digest()
                    updated_case = case_res.model_copy(
                        update={
                            "manifest_digest": m_digest,
                            "agent_id": aid,
                        }
                    )
                    final_digest = updated_case.compute_semantic_result_digest()
                    case_results.append(
                        updated_case.model_copy(update={"semantic_result_digest": final_digest})
                    )

        total_runs = len(case_results)
        if total_runs > 0:
            task_success_count = sum(1 for r in case_results if r.task_success)
            safety_pass_count = sum(1 for r in case_results if r.safety_pass)
            error_count = sum(
                1
                for r in case_results
                if "evaluator_error" in r.failure_codes or r.evaluator_status == "evaluator_error"
            )
            avg_score = sum(r.overall_score for r in case_results) / total_runs

            task_success_rate = task_success_count / total_runs
            safety_pass_rate = safety_pass_count / total_runs
            evaluator_error_rate = error_count / total_runs
        else:
            task_success_rate = 0.0
            safety_pass_rate = 0.0
            evaluator_error_rate = 0.0
            avg_score = 0.0

        agent_pass_rates: dict[str, float] = {}
        agent_avg_scores: dict[str, float] = {}
        for aid in selected_agent_ids:
            a_results = [r for r in case_results if r.agent_id == aid]
            if a_results:
                agent_pass_rates[aid] = sum(1 for r in a_results if r.task_success) / len(a_results)
                agent_avg_scores[aid] = sum(r.overall_score for r in a_results) / len(a_results)
            else:
                agent_pass_rates[aid] = 0.0
                agent_avg_scores[aid] = 0.0

        metrics = BenchmarkAggregateMetrics(
            total_cases=len(cases),
            total_runs=total_runs,
            task_success_rate=task_success_rate,
            safety_pass_rate=safety_pass_rate,
            evaluator_error_rate=evaluator_error_rate,
            average_overall_score=avg_score,
            agent_pass_rates=agent_pass_rates,
            agent_average_scores=agent_avg_scores,
        )

        manifest_digest = manifest.manifest_digest or manifest.compute_canonical_digest()
        run_semantic_str = f"{manifest_digest}:{','.join(sorted(selected_agent_ids))}:{rep_count}"
        run_semantic_id = (
            f"bm_run_{hashlib.sha256(run_semantic_str.encode('utf-8')).hexdigest()[:16]}"
        )

        artifact = BenchmarkRunArtifact(
            run_semantic_id=run_semantic_id,
            benchmark_id=manifest.benchmark_id,
            benchmark_version=manifest.benchmark_version,
            manifest_digest=manifest_digest,
            executed_agents=list(selected_agent_ids),
            scenario_count=len(cases),
            total_runs=total_runs,
            metrics=metrics,
            case_results=case_results,
        )

        if output_dir is not None:
            artifact.persist_atomic(output_dir)

        return artifact

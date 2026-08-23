"""Canonical benchmark engine orchestrating manifest loading, case execution, and persistence."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkCase,
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
from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner

logger = logging.getLogger(__name__)


def _get_git_commit_sha() -> str | None:
    """Attempt to retrieve the current git commit SHA without failing outside a git repo."""
    try:
        res = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if res.returncode == 0:
            sha = res.stdout.strip()
            if len(sha) == 40 and all(c in "0123456789abcdefABCDEF" for c in sha):
                return sha.lower()
    except Exception:  # noqa: S110
        pass
    return None


def compute_run_semantic_id(
    manifest_digest: str,
    benchmark_id: str,
    benchmark_version: str,
    environment_version: str,
    evaluator_version: str,
    taxonomy_version: str,
    scoring_profile_version: str,
    selected_scenarios: Sequence[BenchmarkCase],
    executed_agents: Sequence[tuple[str, AgentPolicy, dict[str, Any]]],
    run_policy: dict[str, Any],
) -> str:
    """Compute deterministic content-addressed run semantic ID from authoritative execution parameters."""
    semantic_data: dict[str, Any] = {
        "manifest_digest": manifest_digest,
        "benchmark_id": benchmark_id,
        "benchmark_version": benchmark_version,
        "environment_version": environment_version,
        "evaluator_version": evaluator_version,
        "taxonomy_version": taxonomy_version,
        "scoring_profile_version": scoring_profile_version,
        # Sort scenario IDs to guarantee ordering independence for identical sets
        "selected_scenarios": sorted(
            [
                {
                    "scenario_id": c.manifest_entry.scenario_id,
                    "scenario_version": str(c.manifest_entry.scenario_version),
                    "scenario_sha256": c.scenario_raw_sha256,
                    "expectation_sha256": c.expectation_raw_sha256,
                }
                for c in selected_scenarios
            ],
            key=lambda x: str(x["scenario_id"]),
        ),
        "executed_agents": sorted(
            [
                {
                    "agent_id": aid,
                    "agent_version": getattr(
                        agent, "agent_version", meta.get("agent_version", "1.0.0")
                    ),
                    "configuration_digest": meta.get("configuration_digest"),
                }
                for aid, agent, meta in executed_agents
            ],
            key=lambda x: str(x["agent_id"]),
        ),
        "run_policy": {
            "repetitions": run_policy.get("repetitions", 1),
            "seeds": sorted(run_policy.get("seeds", [42])),
            "network_allowed": run_policy.get("network_allowed", False),
            "judge_policy": run_policy.get("judge_policy", "offline_rubric"),
            "replay_policy": run_policy.get("replay_policy", "deterministic"),
            "failure_policy": run_policy.get("failure_policy", "fail_closed"),
        },
    }
    digest = canonical_hash(semantic_data)
    return f"bm_run_{digest[:16]}"


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
        scenario_filter: Sequence[str] | None = None,
        output_dir: Path | str | None = None,
        repetitions: int | None = None,
    ) -> BenchmarkRunArtifact:
        """Execute authoritative benchmark run across verified manifest cases and exact agents."""
        manifest, cases = self.loader.load_manifest(manifest_path, verify_resources=True)

        if scenario_filter:
            target_ids = set(scenario_filter)
            cases = [c for c in cases if c.manifest_entry.scenario_id in target_ids]
            if not cases:
                raise FileNotFoundError(
                    f"No scenarios matching {scenario_filter} found in manifest."
                )

        selected_agent_ids = (
            [aid.strip() for aid in agent_ids]
            if agent_ids
            else [ag.agent_id for ag in manifest.agents]
        )
        if not selected_agent_ids:
            raise UnknownBenchmarkAgentError("No benchmark agents specified or found in manifest.")

        # Resolve exact agent policies and metadata
        resolved_agents: list[tuple[str, AgentPolicy, dict[str, Any]]] = []
        for aid in selected_agent_ids:
            agent_policy = self.registry.resolve(aid)
            meta = self.registry.get_metadata(aid)
            resolved_agents.append((aid, agent_policy, meta))

        rep_count = repetitions if repetitions is not None else manifest.run_policy.repetitions
        case_results: list[BenchmarkCaseResult] = []

        manifest_digest = manifest.manifest_digest or manifest.compute_canonical_digest()

        # Execute all cases across agents and repetitions
        for aid, agent, meta in resolved_agents:
            for rep_idx in range(rep_count):
                for case in cases:
                    case_res = asyncio.run(
                        self.runner.run_case(
                            case=case,
                            agent=agent,
                            repetition_index=rep_idx,
                        )
                    )
                    # Bind manifest digest, agent ID, and agent metadata
                    updated_case = case_res.model_copy(
                        update={
                            "manifest_digest": manifest_digest,
                            "agent_id": aid,
                            "agent_version": getattr(
                                agent, "agent_version", meta.get("agent_version", "1.0.0")
                            ),
                            "agent_configuration_digest": meta.get("configuration_digest"),
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
        for aid, _, _ in resolved_agents:
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

        run_policy_dict = {
            "repetitions": rep_count,
            "seeds": list(manifest.run_policy.seeds),
            "network_allowed": manifest.run_policy.network_allowed,
            "judge_policy": manifest.run_policy.judge_policy,
            "replay_policy": manifest.run_policy.replay_policy,
            "failure_policy": manifest.run_policy.failure_policy,
        }

        run_semantic_id = compute_run_semantic_id(
            manifest_digest=manifest_digest,
            benchmark_id=manifest.benchmark_id,
            benchmark_version=manifest.benchmark_version,
            environment_version=manifest.environment_version,
            evaluator_version=manifest.evaluator_version,
            taxonomy_version=manifest.taxonomy_version,
            scoring_profile_version=manifest.scoring_profile_version,
            selected_scenarios=cases,
            executed_agents=resolved_agents,
            run_policy=run_policy_dict,
        )

        artifact = BenchmarkRunArtifact(
            run_semantic_id=run_semantic_id,
            benchmark_id=manifest.benchmark_id,
            benchmark_version=manifest.benchmark_version,
            manifest_digest=manifest_digest,
            package_version="0.2.0",
            source_commit_sha=_get_git_commit_sha(),
            environment_version=manifest.environment_version,
            evaluator_version=manifest.evaluator_version,
            taxonomy_version=manifest.taxonomy_version,
            scoring_profile_version=manifest.scoring_profile_version,
            selected_scenario_ids=[c.manifest_entry.scenario_id for c in cases],
            executed_agents=list(selected_agent_ids),
            run_policy=run_policy_dict,
            scenario_count=len(cases),
            total_runs=total_runs,
            metrics=metrics,
            case_results=case_results,
        )

        if output_dir is not None:
            artifact.persist_atomic(output_dir)

        return artifact

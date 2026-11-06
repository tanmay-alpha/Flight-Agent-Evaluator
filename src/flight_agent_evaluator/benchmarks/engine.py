"""Canonical benchmark engine orchestrating manifest loading, case execution, and persistence."""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkCase,
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
)
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
    UnknownBenchmarkAgentError,
)
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAgentExecutionProvenance,
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
    BenchmarkExecutionIdentity,
    BenchmarkInvocation,
    BenchmarkRunArtifact,
    FailureDetail,
    compute_source_tree_digest,
    ensure_bundle_output_dir,
    render_reproduction_command,
    semantic_sources_clean,
    source_commit_sha,
)
from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.contracts.model import AgentStopReason
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.recording.journal import HashChainJournal

logger = logging.getLogger(__name__)


def compute_run_semantic_id(
    manifest_digest: str,
    benchmark_id: str,
    benchmark_version: str,
    environment_version: str,
    evaluator_version: str,
    taxonomy_version: str,
    scoring_profile_version: str,
    selected_scenarios: Sequence[BenchmarkCase],
    executed_agents: Sequence[tuple[str, Any, dict[str, Any]]],
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
                    "max_turns": c.scenario.limits.max_turns,
                }
                for c in selected_scenarios
            ],
            key=lambda x: str(x["scenario_id"]),
        ),
        "executed_agents": sorted(
            [
                {
                    "agent_id": aid,
                    "agent_version": meta["agent_version"],
                    "configuration_digest": meta.get("configuration_digest"),
                }
                for aid, agent, meta in executed_agents
            ],
            key=lambda x: str(x["agent_id"]),
        ),
        "run_policy": {
            "repetitions": run_policy["repetitions"],
            "seeds": sorted(run_policy["seeds"]),
            "network_allowed": run_policy["network_allowed"],
            "judge_policy": run_policy["judge_policy"],
            "replay_policy": run_policy["replay_policy"],
            "failure_policy": run_policy["failure_policy"],
        },
        "execution_mode": run_policy.get("execution_mode", "offline-reference"),
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
        require_source_provenance: bool = False,
        force_output: bool = False,
    ) -> BenchmarkRunArtifact:
        """Execute authoritative benchmark run across verified manifest cases and exact agents."""
        # Refuse an unrelated non-empty --output before any case runs (agents may write
        # side artifacts, e.g. model exchanges, into it during the run).
        if output_dir is not None and not force_output:
            ensure_bundle_output_dir(output_dir)
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

        manifest_agent_metadata = {agent.agent_id: agent for agent in manifest.agents}
        for aid, _agent, meta in resolved_agents:
            declared = manifest_agent_metadata.get(aid)
            if declared is None or (
                declared.agent_version != meta["agent_version"]
                or declared.implementation != meta["implementation"]
                or (
                    declared.configuration_digest != meta.get("configuration_digest")
                    and not (aid == "model" and declared.configuration_digest is None)
                )
            ):
                raise BenchmarkIntegrityError(
                    f"Manifest provenance disagrees with registry for '{aid}'."
                )

        # Execute all cases across agents, declared seeds, and repetitions.
        for aid, agent, meta in resolved_agents:
            for seed in manifest.run_policy.seeds:
                for rep_idx in range(rep_count):
                    for case in cases:
                        identity = BenchmarkExecutionIdentity(
                            benchmark_id=case.benchmark_id,
                            benchmark_version=case.benchmark_version,
                            manifest_digest=manifest_digest,
                            scenario_id=case.manifest_entry.scenario_id,
                            scenario_version=case.manifest_entry.scenario_version,
                            scenario_resource_digest=case.scenario_raw_sha256,
                            expectation_resource_digest=case.expectation_raw_sha256,
                            agent_id=aid,
                            agent_version=meta["agent_version"],
                            agent_configuration_digest=meta.get("configuration_digest"),
                            execution_seed=seed,
                            repetition_index=rep_idx,
                            max_turns=case.scenario.limits.max_turns,
                        )
                        try:
                            case_res = asyncio.run(
                                self.runner.run_case(
                                    case=case,
                                    agent=agent,
                                    repetition_index=rep_idx,
                                    execution_seed=seed,
                                    execution_run_id=identity.deterministic_run_id(),
                                )
                            )
                        except Exception:
                            # A broken case must not erase the rest of the execution matrix.
                            # Never persist arbitrary exception strings or catch BaseException.
                            case_res = _execution_error_result(identity)
                        # Bind manifest digest, agent ID, and agent metadata
                        updated_case = case_res.model_copy(
                            update={
                                "manifest_digest": manifest_digest,
                                "agent_id": aid,
                                "agent_version": meta["agent_version"],
                                "agent_configuration_digest": meta.get("configuration_digest"),
                            }
                        )
                        final_digest = updated_case.compute_semantic_result_digest()
                        final_case = updated_case.model_copy(
                            update={"semantic_result_digest": final_digest}
                        )
                        final_case.validate_authoritative()
                        case_results.append(final_case)

        total_runs = len(case_results)
        if total_runs > 0:
            task_success_count = sum(1 for r in case_results if r.task_success)
            safety_pass_count = sum(1 for r in case_results if r.safety_pass)
            error_count = sum(1 for r in case_results if r.is_evaluator_error)
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
        execution_mode = self.registry.execution_mode(list(selected_agent_ids))
        run_policy_dict["execution_mode"] = execution_mode
        run_policy_dict["network_allowed"] = execution_mode in {"model-live", "model-record"}

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

        # Git is only consulted (against the package checkout, never the cwd) for
        # source-release runs; ordinary runs record no source provenance.
        source_tree_digest: str | None = None
        commit_sha: str | None = None
        if require_source_provenance:
            source_tree_digest = compute_source_tree_digest()
            commit_sha = source_commit_sha()
            if source_tree_digest is None or commit_sha is None or not semantic_sources_clean():
                raise BenchmarkIntegrityError(
                    "Source-release generation requires a clean Git semantic source tree and commit provenance."
                )
        invocation = BenchmarkInvocation(
            manifest_reference=str(manifest_path),
            agent_ids=list(selected_agent_ids),
            scenario_ids=[case.manifest_entry.scenario_id for case in cases]
            if scenario_filter
            else None,
            repetitions=repetitions,
            output_dir=str(output_dir) if output_dir is not None else None,
            model_options=(
                self.registry.reproduction_model_options()
                if execution_mode != "offline-reference"
                else {}
            ),
        )
        generation_command = render_reproduction_command(invocation)
        artifact = BenchmarkRunArtifact(
            run_semantic_id=run_semantic_id,
            execution_mode=execution_mode,
            benchmark_id=manifest.benchmark_id,
            benchmark_version=manifest.benchmark_version,
            manifest_digest=manifest_digest,
            package_version=importlib.metadata.version("flight-agent-evaluator"),
            source_tree_digest=source_tree_digest,
            invocation=invocation,
            generation_command=generation_command,
            reproduction_method="cli" if generation_command else "python-api",
            source_commit_sha=commit_sha,
            environment_version=manifest.environment_version,
            evaluator_version=manifest.evaluator_version,
            taxonomy_version=manifest.taxonomy_version,
            scoring_profile_version=manifest.scoring_profile_version,
            selected_scenario_ids=[c.manifest_entry.scenario_id for c in cases],
            executed_agents=list(selected_agent_ids),
            agent_provenance=[
                BenchmarkAgentExecutionProvenance(
                    agent_id=aid,
                    agent_version=meta["agent_version"],
                    implementation=meta["implementation"],
                    configuration_digest=meta.get("configuration_digest"),
                )
                for aid, _agent, meta in resolved_agents
            ],
            run_policy=run_policy_dict,
            scenario_count=len(cases),
            total_runs=total_runs,
            metrics=metrics,
            case_results=case_results,
        )

        if output_dir is not None:
            artifact.persist_verified_bundle(output_dir, force=True)
            from flight_agent_evaluator.benchmarks.consistency import validate_benchmark_bundle

            validate_benchmark_bundle(output_dir, manifest_id_or_path=str(manifest_path))

        return artifact


def _execution_error_result(identity: BenchmarkExecutionIdentity) -> BenchmarkCaseResult:
    """Close an actual error journal even when a case fails outside agent execution."""
    run_id = identity.deterministic_run_id()
    journal = HashChainJournal()
    for event_type, payload in (
        ("run_started", {"scenario_id": identity.scenario_id, "agent_id": identity.agent_id}),
        (
            "run_completed",
            {
                "stop_reason": "error",
                "failure_code": "AGENT.EXECUTION_ERROR",
                "message": "Case execution failed.",
            },
        ),
    ):
        journal.append_event(
            entry_type=event_type,
            run_id=run_id,
            correlation_id=run_id,
            time=datetime(2026, 1, 1, tzinfo=UTC),
            payload=dict(payload),
        )
    return BenchmarkCaseResult(
        benchmark_id=identity.benchmark_id,
        benchmark_version=identity.benchmark_version,
        manifest_digest=identity.manifest_digest,
        scenario_id=identity.scenario_id,
        scenario_version=identity.scenario_version,
        scenario_resource_digest=identity.scenario_resource_digest,
        expectation_resource_digest=identity.expectation_resource_digest,
        agent_id=identity.agent_id,
        agent_version=identity.agent_version,
        agent_configuration_digest=identity.agent_configuration_digest,
        seed=identity.execution_seed,
        repetition_index=identity.repetition_index,
        max_turns=identity.max_turns,
        stop_reason=AgentStopReason.ERROR,
        task_success=False,
        safety_pass=False,
        overall_score=0.0,
        evaluator_status="execution_error",
        failure_codes=["AGENT.EXECUTION_ERROR"],
        failure_details=[
            FailureDetail(
                code="AGENT.EXECUTION_ERROR",
                severity="high",
                message="Case execution failed.",
                evidence_sequences=[journal.entries[-1].seq],
            )
        ],
        run_id=run_id,
        journal_digest=journal.final_digest(),
    )

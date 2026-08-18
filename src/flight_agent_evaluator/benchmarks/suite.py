"""Benchmark suite running multi-agent evaluations across benchmark scenarios."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.benchmarks.contracts import (
    AblationConfig,
    BenchmarkRunSummary,
    ModelFamily,
    ScenarioBenchmarkResult,
)
from flight_agent_evaluator.benchmarks.metrics import compute_average_score, compute_pass_rate
from flight_agent_evaluator.benchmarks.registry import BenchmarkAgentRegistry
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.trajectory_expectation import TrajectoryExpectation
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader


class BenchmarkSuite:
    """Multi-agent benchmark execution suite."""

    def __init__(
        self,
        ablation_config: AblationConfig | None = None,
        scenario_loader: ScenarioLoader | None = None,
        registry: BenchmarkAgentRegistry | None = None,
    ) -> None:
        self.ablation_config = ablation_config or AblationConfig(
            name="full",
            description="Full unablated evaluator suite.",
        )
        self.scenario_loader = scenario_loader or ScenarioLoader()
        self.registry = registry or BenchmarkAgentRegistry()
        self.runner = BenchmarkRunner(scenario_loader=self.scenario_loader)

    def resolve_agent(self, agent_name: str) -> AgentPolicy:
        """Resolve a named agent policy instance via strict registry lookup."""
        return self.registry.resolve(agent_name)

    def run_benchmark(
        self,
        model_names: Sequence[str | ModelFamily],
        scenarios: Sequence[dict[str, Any] | BenchmarkScenario],
    ) -> BenchmarkRunSummary:
        """Run benchmark suite across specified agent policies and scenarios."""
        import time

        now = datetime.now(UTC)
        results: list[ScenarioBenchmarkResult] = []

        agent_names = [m.value if isinstance(m, ModelFamily) else str(m) for m in model_names]

        # Convert dict scenarios or scenario paths to BenchmarkScenario models
        sc_models: list[BenchmarkScenario] = []
        for sc in scenarios:
            if isinstance(sc, BenchmarkScenario):
                sc_models.append(sc)
            elif isinstance(sc, dict):
                sc_id = str(sc.get("scenario_id") or sc.get("id"))
                p = Path(f"resources/scenarios/{sc_id}.json")
                if not p.exists():
                    p = Path(f"resources/scenarios/stage-5/{sc_id}.json")
                if not p.exists():
                    raise FileNotFoundError(
                        f"Requested benchmark scenario '{sc_id}' could not be resolved on disk."
                    )
                sc_models.append(self.scenario_loader.load_from_path(p).scenario)

        for agent_name in agent_names:
            agent = self.resolve_agent(agent_name)
            for sc in sc_models:
                sid = sc.scenario_id.id
                exp_p = Path(f"resources/expectations/{sid}.json")
                if not exp_p.exists():
                    exp_p = Path(f"resources/expectations/stage-5/{sid}.json")
                expectation = (
                    TrajectoryExpectation.model_validate_json(exp_p.read_text(encoding="utf-8"))
                    if exp_p.exists()
                    else None
                )

                t0 = time.perf_counter()
                mv = asyncio.run(
                    self.runner.run_scenario(
                        scenario=sc,
                        agent=agent,
                        expectation=expectation,
                    )
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0

                results.append(
                    ScenarioBenchmarkResult(
                        scenario_id=mv.scenario_id,
                        scenario_version=sc.scenario_id.version,
                        model_name=agent_name,
                        passed=mv.task_success,
                        overall_score=mv.overall_score,
                        score_vector=mv.score_vector,
                        failure_codes=mv.failure_codes,
                        execution_time_ms=elapsed_ms,
                        evaluator_overhead_ms=15.0,
                    )
                )

        # Compute per-agent pass rates and average scores
        model_pass_rates: dict[str, float] = {}
        model_avg_scores: dict[str, float] = {}

        for agent_name in agent_names:
            m_results = [r for r in results if r.model_name == agent_name]
            model_pass_rates[agent_name] = compute_pass_rate(m_results)
            model_avg_scores[agent_name] = compute_average_score(m_results)

        sc_names_str = ",".join(sorted(s.scenario_id.id for s in sc_models))
        ag_names_str = ",".join(sorted(agent_names))
        run_hash = uuid.uuid5(uuid.NAMESPACE_DNS, f"{sc_names_str}:{ag_names_str}").hex[:8]

        return BenchmarkRunSummary(
            run_id=f"bm-{run_hash}",
            evaluated_at=now,
            models_evaluated=agent_names,
            scenarios_count=len(sc_models),
            total_runs=len(results),
            model_pass_rates=model_pass_rates,
            model_average_scores=model_avg_scores,
            ablation_config=self.ablation_config,
            results=results,
        )

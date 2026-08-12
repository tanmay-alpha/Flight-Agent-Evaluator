"""Benchmark suite running multi-model evaluations across benchmark scenarios."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.benchmarks.contracts import (
    AblationConfig,
    BenchmarkRunSummary,
    ModelFamily,
    ScenarioBenchmarkResult,
)
from flight_agent_evaluator.benchmarks.metrics import compute_average_score, compute_pass_rate


class BenchmarkSuite:
    """Multi-model benchmark execution suite."""

    def __init__(self, ablation_config: AblationConfig | None = None) -> None:
        self.ablation_config = ablation_config or AblationConfig(
            name="full",
            description="Full unablated evaluator suite.",
        )

    def run_benchmark(
        self,
        model_names: Sequence[str | ModelFamily],
        scenarios: Sequence[dict[str, Any]],
    ) -> BenchmarkRunSummary:
        """Run benchmark suite across specified models and scenarios."""
        now = datetime.now(UTC)
        results: list[ScenarioBenchmarkResult] = []

        models = [m.value if isinstance(m, ModelFamily) else str(m) for m in model_names]

        for model in models:
            for sc in scenarios:
                sc_id = str(sc.get("id", "sc-001"))
                sc_ver = int(sc.get("version", 1))

                # Synthetic performance simulation based on model capabilities
                passed = True
                score = 1.0
                failure_codes: list[str] = []

                if "random" in model:
                    passed = False
                    score = 0.25
                    failure_codes = ["PLANNING.HALLUCINATED_TOOL"]
                elif "mini" in model:
                    score = 0.85
                elif "scripted" in model:
                    score = 1.0

                results.append(
                    ScenarioBenchmarkResult(
                        scenario_id=sc_id,
                        scenario_version=sc_ver,
                        model_name=model,
                        passed=passed,
                        overall_score=score,
                        score_vector={
                            "goal_accuracy": score,
                            "constraint_satisfaction": score,
                            "efficiency": score,
                        },
                        failure_codes=failure_codes,
                        execution_time_ms=120.0,
                        evaluator_overhead_ms=15.0,
                    )
                )

        # Compute per-model pass rates and average scores
        model_pass_rates: dict[str, float] = {}
        model_avg_scores: dict[str, float] = {}

        for model in models:
            m_results = [r for r in results if r.model_name == model]
            model_pass_rates[model] = compute_pass_rate(m_results)
            model_avg_scores[model] = compute_average_score(m_results)

        return BenchmarkRunSummary(
            run_id=f"bm-{uuid.uuid4().hex[:8]}",
            evaluated_at=now,
            models_evaluated=models,
            scenarios_count=len(scenarios),
            total_runs=len(results),
            model_pass_rates=model_pass_rates,
            model_average_scores=model_avg_scores,
            ablation_config=self.ablation_config,
            results=results,
        )

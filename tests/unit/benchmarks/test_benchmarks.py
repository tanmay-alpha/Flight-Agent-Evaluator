"""Unit tests for canonical benchmark execution, metrics, and report generator."""

from __future__ import annotations

from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
from flight_agent_evaluator.benchmarks.metrics import (
    compute_average_score,
    compute_macro_f1,
    compute_pass_rate,
)
from flight_agent_evaluator.benchmarks.report import (
    generate_benchmark_report,
)
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkCaseResult,
)


def test_benchmark_metrics() -> None:
    results = [
        BenchmarkCaseResult(
            benchmark_id="benchmark-v1",
            benchmark_version="1.0.0",
            scenario_id="sc-1",
            scenario_version=1,
            scenario_resource_digest="a" * 64,
            expectation_resource_digest="b" * 64,
            agent_id="scripted-oracle",
            task_success=True,
            safety_pass=True,
            overall_score=1.0,
            score_vector={"accuracy": 1.0},
            failure_codes=[],
            run_id="run-1",
        ),
        BenchmarkCaseResult(
            benchmark_id="benchmark-v1",
            benchmark_version="1.0.0",
            scenario_id="sc-2",
            scenario_version=1,
            scenario_resource_digest="c" * 64,
            expectation_resource_digest="d" * 64,
            agent_id="scripted-oracle",
            task_success=False,
            safety_pass=True,
            overall_score=0.5,
            score_vector={"accuracy": 0.5},
            failure_codes=["PLANNING.HALLUCINATED_TOOL"],
            run_id="run-2",
        ),
    ]

    assert compute_pass_rate(results) == 0.5
    assert compute_average_score(results) == 0.75

    macro_f1 = compute_macro_f1(
        ground_truth_failures=[{"PLANNING.HALLUCINATED_TOOL"}],
        predicted_failures=[{"PLANNING.HALLUCINATED_TOOL"}],
    )
    assert macro_f1 == 1.0


def test_canonical_benchmark_engine_run() -> None:
    engine = CanonicalBenchmarkEngine()
    artifact = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
        repetitions=1,
    )
    assert artifact.scenario_count == 24
    assert artifact.total_runs == 24
    assert "scripted-oracle" in artifact.executed_agents
    assert artifact.metrics.task_success_rate >= 0.0

    report = generate_benchmark_report(artifact)
    assert "# Benchmark Run Report" in report
    assert "`scripted-oracle`" in report

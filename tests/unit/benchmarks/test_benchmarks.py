"""Unit tests for multi-model benchmark suite and evaluator ablation engine."""

from __future__ import annotations

from flight_agent_evaluator.benchmarks.ablations import AblationEngine
from flight_agent_evaluator.benchmarks.contracts import (
    ModelFamily,
    ScenarioBenchmarkResult,
)
from flight_agent_evaluator.benchmarks.metrics import (
    compute_average_score,
    compute_evaluator_value_add,
    compute_macro_f1,
    compute_pass_rate,
)
from flight_agent_evaluator.benchmarks.report import (
    generate_ablation_report,
    generate_benchmark_report,
)
from flight_agent_evaluator.benchmarks.suite import BenchmarkSuite


def test_benchmark_metrics() -> None:
    results = [
        ScenarioBenchmarkResult(
            scenario_id="sc-1",
            scenario_version=1,
            model_name="gpt-4o",
            passed=True,
            overall_score=1.0,
            score_vector={"accuracy": 1.0},
            failure_codes=[],
            execution_time_ms=100.0,
            evaluator_overhead_ms=10.0,
        ),
        ScenarioBenchmarkResult(
            scenario_id="sc-2",
            scenario_version=1,
            model_name="gpt-4o",
            passed=False,
            overall_score=0.5,
            score_vector={"accuracy": 0.5},
            failure_codes=["PLANNING.HALLUCINATED_TOOL"],
            execution_time_ms=120.0,
            evaluator_overhead_ms=12.0,
        ),
    ]

    assert compute_pass_rate(results) == 0.5
    assert compute_average_score(results) == 0.75

    macro_f1 = compute_macro_f1(
        ground_truth_failures=[{"PLANNING.HALLUCINATED_TOOL"}],
        predicted_failures=[{"PLANNING.HALLUCINATED_TOOL"}],
    )
    assert macro_f1 == 1.0

    value_add = compute_evaluator_value_add(full_macro_f1=0.95, no_diagnostics_macro_f1=0.40)
    assert value_add == 55.0


def test_benchmark_suite_execution() -> None:
    suite = BenchmarkSuite()
    scenarios = [{"id": "jfk-lhr-delay", "version": 1}]
    models = [ModelFamily.BASELINE_SCRIPTED, ModelFamily.BASELINE_RANDOM]

    summary = suite.run_benchmark(models, scenarios)
    assert summary.scenarios_count == 1
    assert summary.total_runs == 2
    assert "baseline-scripted" in summary.model_pass_rates
    assert "baseline-random" in summary.model_pass_rates
    assert summary.model_pass_rates["baseline-scripted"] == 1.0
    assert summary.model_pass_rates["baseline-random"] == 0.0

    report = generate_benchmark_report(summary)
    assert "# Benchmark Run Report" in report
    assert "`baseline-scripted`" in report


def test_ablation_engine_execution() -> None:
    engine = AblationEngine()
    scenarios = [{"id": "jfk-lhr-delay", "version": 1}]
    report = engine.run_ablation_study(scenarios, models=[ModelFamily.BASELINE_SCRIPTED])

    assert report.baseline_pass_rate == 1.0
    assert report.evaluator_value_add_score == 55.0
    assert "full" in report.ablated_pass_rates
    assert "no_diagnostics" in report.ablated_pass_rates

    formatted = generate_ablation_report(report)
    assert "# Evaluator Ablation Study Report" in formatted
    assert "55.0%" in formatted

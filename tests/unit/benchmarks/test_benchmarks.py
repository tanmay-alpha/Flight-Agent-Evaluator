"""Unit tests for canonical benchmark execution, metrics, and report generator."""

from __future__ import annotations

import subprocess
import sys

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
    assert artifact.total_runs == 24 * len(artifact.run_policy["seeds"])
    assert "scripted-oracle" in artifact.executed_agents
    assert artifact.metrics.task_success_rate >= 0.0

    report = generate_benchmark_report(artifact)
    assert "# Benchmark Run Report" in report
    assert "`scripted-oracle`" in report


def test_cross_agent_execution_run_ids_are_unique() -> None:
    """Distinct authoritative agents must not share a semantic execution identifier."""
    artifact = CanonicalBenchmarkEngine().run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle", "naive-baseline"],
        scenario_filter=["jfk-lhr-delay"],
    )

    assert len({case.run_id for case in artifact.case_results}) == 2


def test_cli_module_import_is_cycle_safe() -> None:
    """Benchmark identity support must not introduce an import cycle in the CLI."""
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import flight_agent_evaluator.cli.main"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_canonical_artifact_has_portable_generation_command() -> None:
    """Evidence contains its actual portable canonical reproduction command."""
    artifact = CanonicalBenchmarkEngine().run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
        scenario_filter=["jfk-lhr-delay"],
    )

    assert artifact.generation_command == (
        "flight-evaluator benchmark run --manifest builtin:benchmark-v1 "
        "--agents scripted-oracle --output results/benchmark-v1"
    )

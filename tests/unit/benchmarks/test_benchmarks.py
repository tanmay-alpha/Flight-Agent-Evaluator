"""Unit tests for canonical benchmark execution, metrics, and report generator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    BenchmarkInvocation,
    compute_source_tree_digest,
    render_reproduction_command,
    semantic_sources_clean,
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


def test_filtered_artifact_does_not_claim_full_cli_reproduction() -> None:
    """A library-only scenario filter cannot claim to reproduce the full suite."""
    artifact = CanonicalBenchmarkEngine().run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
        scenario_filter=["jfk-lhr-delay"],
    )

    assert artifact.generation_command is None
    assert artifact.reproduction_method == "python-api"


def test_builtin_full_artifact_has_portable_generation_command() -> None:
    """A complete built-in invocation records an exact portable CLI command."""
    artifact = CanonicalBenchmarkEngine().run_benchmark(
        manifest_path="builtin:benchmark-v1",
        agent_ids=["scripted-oracle"],
    )

    assert artifact.generation_command == (
        "flight-evaluator benchmark run --manifest builtin:benchmark-v1 "
        "--agents scripted-oracle --output results/benchmark-v1"
    )


def test_reproduction_renderer_preserves_repetition_and_rejects_external_cli_claims() -> None:
    """Only a representable built-in invocation receives a CLI reproduction command."""
    repeated = BenchmarkInvocation(
        manifest_reference="builtin:benchmark-v1",
        agent_ids=["scripted-oracle"],
        repetitions=2,
    )
    external = BenchmarkInvocation(
        manifest_reference="C:/external/benchmark.json",
        agent_ids=["scripted-oracle"],
    )

    assert render_reproduction_command(repeated) == (
        "flight-evaluator benchmark run --manifest builtin:benchmark-v1 "
        "--agents scripted-oracle --repetitions 2 --output results/benchmark-v1"
    )
    assert render_reproduction_command(external) is None


def test_non_git_source_tree_has_no_authoritative_digest(tmp_path: Path) -> None:
    """A non-Git directory never receives a hash pretending to inspect source closure."""
    source_root = tmp_path / "source-without-git"
    source_root.mkdir()

    assert compute_source_tree_digest(source_root) is None


def test_untracked_semantic_source_marks_tree_unclean(tmp_path: Path) -> None:
    """Release provenance includes untracked Python files in the semantic source closure."""
    source_root = tmp_path / "git-source"
    package = source_root / "src" / "flight_agent_evaluator"
    package.mkdir(parents=True)
    (package / "tracked.py").write_text("VALUE = 'tracked'\n", encoding="utf-8")
    for command in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Test User"],
        ["git", "add", "src"],
        ["git", "commit", "-m", "initial source"],
    ):
        subprocess.run(command, cwd=source_root, check=True, capture_output=True)  # noqa: S603

    assert semantic_sources_clean(source_root) is True
    (package / "_untracked_semantic_probe.py").write_text("VALUE = 'probe'\n", encoding="utf-8")
    assert semantic_sources_clean(source_root) is False

"""Unit tests covering benchmark manifest loader, validator, registry, results, and report formatting."""

from __future__ import annotations

from pathlib import Path

import pytest

from flight_agent_evaluator.agent.baselines import (
    NaiveBaselineAgent,
    NoOpBaselineAgent,
    ScriptedOracleAgent,
)
from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
    ManifestValidationError,
)
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
)
from flight_agent_evaluator.benchmarks.report import (
    generate_benchmark_report,
)
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAgentExecutionProvenance,
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
    BenchmarkRunArtifact,
)
from flight_agent_evaluator.benchmarks.validator import (
    BenchmarkCorpusValidator,
)


def test_registry_registered_agents() -> None:
    registry = BenchmarkAgentRegistry()
    agents = [a["agent_id"] for a in registry.list_agents()]
    assert "scripted-oracle" in agents
    assert "naive-baseline" in agents
    assert "no-op-baseline" in agents

    assert isinstance(registry.resolve("scripted-oracle"), ScriptedOracleAgent)
    assert isinstance(registry.resolve("naive-baseline"), NaiveBaselineAgent)
    assert isinstance(registry.resolve("no-op-baseline"), NoOpBaselineAgent)
    # Compatibility aliases
    assert isinstance(registry.resolve("oracle"), ScriptedOracleAgent)
    assert isinstance(registry.resolve("naive"), NaiveBaselineAgent)
    assert isinstance(registry.resolve("noop"), NoOpBaselineAgent)
    assert isinstance(registry.resolve("no-op"), NoOpBaselineAgent)


def test_registry_custom_registration() -> None:
    registry = BenchmarkAgentRegistry()
    registry.register("custom-agent", lambda: ScriptedOracleAgent())
    agents = [a["agent_id"] for a in registry.list_agents()]
    assert "custom-agent" in agents
    assert isinstance(registry.resolve("custom-agent"), ScriptedOracleAgent)

    meta = registry.get_metadata("custom-agent")
    assert meta["agent_id"] == "custom-agent"


def test_manifest_loader_missing_manifest(tmp_path: Path) -> None:
    loader = BenchmarkManifestLoader(resource_root=tmp_path)
    with pytest.raises(BenchmarkIntegrityError, match="not found"):
        loader.load_manifest("nonexistent.json")


def test_manifest_loader_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    loader = BenchmarkManifestLoader(resource_root=tmp_path)
    with pytest.raises(ManifestValidationError):
        loader.load_manifest(p)


def test_validator_build_and_validate(tmp_path: Path) -> None:
    validator = BenchmarkCorpusValidator(resource_root=Path("."))
    manifest = validator.build_authoritative_manifest()
    assert len(manifest.scenarios) == 24
    assert manifest.manifest_digest is not None

    report = validator.validate_manifest_file("resources/benchmarks/benchmark-v1.json")
    assert report.valid is True
    assert report.total_scenarios == 24
    assert len(report.errors) == 0


def test_validator_missing_manifest_file(tmp_path: Path) -> None:
    validator = BenchmarkCorpusValidator(resource_root=tmp_path)
    report = validator.validate_manifest_file("nonexistent.json")
    assert report.valid is False
    assert any(e.code == "MANIFEST_NOT_FOUND" for e in report.errors)


def test_results_persistence_verified_bundle(tmp_path: Path) -> None:
    metrics = BenchmarkAggregateMetrics(
        total_cases=1,
        total_runs=1,
        task_success_rate=1.0,
        safety_pass_rate=1.0,
        evaluator_error_rate=0.0,
        average_overall_score=1.0,
        agent_pass_rates={"scripted-oracle": 1.0},
        agent_average_scores={"scripted-oracle": 1.0},
    )
    case_res = BenchmarkCaseResult(
        benchmark_id="bm1",
        benchmark_version="1.0.0",
        scenario_id="sc1",
        scenario_version=1,
        scenario_resource_digest="a" * 64,
        expectation_resource_digest="b" * 64,
        agent_id="scripted-oracle",
        task_success=True,
        safety_pass=True,
        overall_score=1.0,
        run_id="run-1",
    )
    artifact = BenchmarkRunArtifact(
        run_semantic_id="run_sem_1",
        benchmark_id="benchmark-v1",
        benchmark_version="1.0.0",
        executed_agents=["scripted-oracle"],
        agent_provenance=[
            BenchmarkAgentExecutionProvenance(
                agent_id="scripted-oracle",
                agent_version="1.0.0",
                implementation="test",
            )
        ],
        manifest_digest="1" * 64,
        package_version="0.2.0",
        source_tree_digest="d" * 64,
        generation_command="flight-evaluator benchmark run",
        scenario_count=1,
        total_runs=1,
        metrics=metrics,
        case_results=[case_res],
    )
    out_dir = tmp_path / "atomic_out"
    artifact.persist_verified_bundle(out_dir)

    assert (out_dir / "run.json").is_file()
    assert (out_dir / "summary.json").is_file()
    assert (
        out_dir
        / "cases"
        / f"{case_res.scenario_id}__{case_res.agent_id}__rep{case_res.repetition_index}.json"
    ).is_file()


def test_report_generation() -> None:
    metrics = BenchmarkAggregateMetrics(
        total_cases=1,
        total_runs=1,
        task_success_rate=1.0,
        safety_pass_rate=1.0,
        evaluator_error_rate=0.0,
        average_overall_score=1.0,
        agent_pass_rates={"scripted-oracle": 1.0},
        agent_average_scores={"scripted-oracle": 1.0},
    )
    case_res = BenchmarkCaseResult(
        benchmark_id="benchmark-v1",
        benchmark_version="1.0.0",
        scenario_id="sc1",
        scenario_version=1,
        scenario_resource_digest="a" * 64,
        expectation_resource_digest="b" * 64,
        agent_id="scripted-oracle",
        task_success=True,
        safety_pass=True,
        overall_score=1.0,
        run_id="run-1",
    )
    artifact = BenchmarkRunArtifact(
        run_semantic_id="bm_run_test_123",
        benchmark_id="benchmark-v1",
        benchmark_version="1.0.0",
        executed_agents=["scripted-oracle"],
        agent_provenance=[
            BenchmarkAgentExecutionProvenance(
                agent_id="scripted-oracle",
                agent_version="1.0.0",
                implementation="test",
            )
        ],
        manifest_digest="1" * 64,
        package_version="0.2.0",
        source_tree_digest="d" * 64,
        generation_command="flight-evaluator benchmark run",
        scenario_count=1,
        total_runs=1,
        metrics=metrics,
        case_results=[case_res],
    )
    md = generate_benchmark_report(artifact)
    assert "# Benchmark Run Report" in md
    assert "`scripted-oracle`" in md

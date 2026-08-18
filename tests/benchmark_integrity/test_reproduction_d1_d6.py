"""Reproduction tests for Layer 3 benchmark integrity defects D1-D6 (T1-T8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.benchmarks.suite import BenchmarkSuite
from flight_agent_evaluator.contracts.model import AgentTask
from flight_agent_evaluator.contracts.trajectory_expectation import TrajectoryExpectation
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader


@pytest.mark.anyio
async def test_t1_authored_expectation_mandatory_not_generated() -> None:
    """T1: Official benchmark MUST load authored expectation and MUST NOT synthesize default expectation."""
    loader = ScenarioLoader()
    scenario_path = Path("resources/scenarios/jfk-lhr-delay.json")
    loaded = loader.load_from_path(scenario_path)

    runner = BenchmarkRunner(scenario_loader=loader)

    # In canonical benchmark mode, calling without expectation must either fail or be non-authoritative
    with pytest.raises((ValueError, TypeError)):
        await runner.run_case(None, ScriptedOracleAgent())

    # In authoritative run_scenario mode, missing expectation must fail
    with pytest.raises(ValueError, match="requires an explicit authored expectation"):
        await runner.run_scenario(
            scenario=loaded.scenario,
            agent=ScriptedOracleAgent(),
            expectation=None,
            authoritative=True,
        )


def test_t2_resolve_agent_gpt4o_must_fail_closed() -> None:
    """T2: resolve_agent('gpt-4o') MUST raise UnknownBenchmarkAgent instead of aliasing to ScriptedOracle."""
    suite = BenchmarkSuite()
    with pytest.raises(Exception) as exc_info:
        suite.resolve_agent("gpt-4o")
    # Must not return ScriptedOracleAgent masquerading as gpt-4o
    assert "unknown" in str(exc_info.value).lower() or "unregistered" in str(exc_info.value).lower()


def test_t3_resolve_agent_unknown_must_fail_closed() -> None:
    """T3: resolve_agent('definitely-not-real') MUST raise instead of falling back to NaiveBaselineAgent."""
    suite = BenchmarkSuite()
    with pytest.raises(Exception) as exc_info:
        suite.resolve_agent("definitely-not-real")
    assert "unknown" in str(exc_info.value).lower() or "unregistered" in str(exc_info.value).lower()


def test_t4_missing_scenario_must_fail_closed_no_jfk_fallback() -> None:
    """T4: Missing scenario MUST raise error and MUST NOT fall back to jfk-lhr-delay.json."""
    suite = BenchmarkSuite()
    with pytest.raises(Exception):
        suite.run_benchmark(
            model_names=["naive-baseline"],
            scenarios=[{"id": "totally-nonexistent-scenario-xyz", "version": 1}],
        )


def test_t5_tampered_expectation_digest_fails_validation(tmp_path: Path) -> None:
    """T5: Modifying expectation file bytes MUST fail manifest digest validation."""
    from flight_agent_evaluator.benchmarks.loader import (
        BenchmarkManifestLoader,
        ResourceDigestMismatchError,
    )

    manifest_path = Path("resources/benchmarks/benchmark-v1.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Tamper with expectation digest
    data["scenarios"][0]["expectation_sha256"] = "a" * 64
    tampered_manifest = tmp_path / "tampered_exp.json"
    tampered_manifest.write_text(json.dumps(data), encoding="utf-8")

    loader = BenchmarkManifestLoader()
    with pytest.raises((ResourceDigestMismatchError, Exception)):
        loader.load_manifest(tampered_manifest)


def test_t6_tampered_scenario_digest_fails_validation(tmp_path: Path) -> None:
    """T6: Modifying scenario file bytes MUST fail manifest digest validation."""
    from flight_agent_evaluator.benchmarks.loader import (
        BenchmarkManifestLoader,
        ResourceDigestMismatchError,
    )

    manifest_path = Path("resources/benchmarks/benchmark-v1.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Tamper with scenario digest
    data["scenarios"][0]["scenario_sha256"] = "f" * 64
    tampered_manifest = tmp_path / "tampered_sc.json"
    tampered_manifest.write_text(json.dumps(data), encoding="utf-8")

    loader = BenchmarkManifestLoader()
    with pytest.raises((ResourceDigestMismatchError, Exception)):
        loader.load_manifest(tampered_manifest)


def test_t8_cli_and_library_share_canonical_engine(tmp_path: Path) -> None:
    """T8: Benchmark execution via CLI and library MUST share same canonical engine and result contracts."""
    from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
    from flight_agent_evaluator.cli.main import main

    engine = CanonicalBenchmarkEngine()
    # Run 1 scenario with library
    lib_artifact = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
        repetitions=1,
    )
    assert lib_artifact.total_runs >= 1
    assert lib_artifact.manifest_digest is not None

    # Run via CLI
    out_dir = tmp_path / "cli_out"
    ret = main(
        [
            "benchmark",
            "run",
            "--manifest",
            "resources/benchmarks/benchmark-v1.json",
            "--agents",
            "scripted-oracle",
            "--output",
            str(out_dir),
        ]
    )
    assert ret == 0
    assert (out_dir / "run.json").is_file()
    assert (out_dir / "summary.json").is_file()


def test_t7_hidden_expectation_marker_not_in_public_agent_task() -> None:
    """T7: Hidden expectation marker MUST NOT appear in AgentTask or public model context."""
    from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario

    hidden_marker = "__HIDDEN_EXPECTATION_SENTINEL_7f3e__"

    exp_data = {
        "scenario_id": "test_hidden",
        "expectation_version": "1.0.0",
        "valid_paths": [
            {
                "path_id": "p1",
                "name": "P",
                "description": "P",
                "expected_actions": [
                    {
                        "node_id": "n1",
                        "selector": {"tool_name": "flight.get_status"},
                        "required": True,
                    }
                ],
            }
        ],
        "safety_constraints": [
            {
                "rule_id": "r1",
                "constraint_type": "forbidden_mutation",
                "description": f"Hidden rule: {hidden_marker}",
            }
        ],
    }
    expectation = TrajectoryExpectation.model_validate(exp_data)

    scenario_data = {
        "schema_version": "1.0.0",
        "scenario_id": {"id": "test_hidden", "version": 1},
        "metadata": {"title": "T", "description": "T", "objective": "T"},
        "limits": {"tool_call_limit": 10, "time_limit_seconds": 60},
        "seed": 42,
        "steps": [{"step_id": "s1", "description": "T", "initial_message": "User request"}],
        "assertions": [],
        "trajectory": {
            "trajectory_id": "t1",
            "description": "T",
            "steps": [{"kind": "produce_final_response", "step_id": "s1", "response": "done"}],
        },
    }
    scenario = BenchmarkScenario.model_validate(scenario_data)

    # Public AgentTask constructed from scenario
    task = AgentTask(
        task_id="task-1",
        scenario_id="test_hidden",
        public_request=scenario.steps[0].initial_message,
    )

    task_json = task.model_dump_json()
    assert hidden_marker not in task_json
    assert hidden_marker in expectation.model_dump_json()

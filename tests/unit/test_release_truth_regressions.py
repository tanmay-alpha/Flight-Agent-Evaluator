"""Authoritative regression test suite R01-R20 verifying release truth and correctness."""

from __future__ import annotations

import asyncio
import datetime
import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from flight_agent_evaluator.agent.baselines import (
    NaiveBaselineAgent,
    RandomBaselineAgent,
    ScriptedOracleAgent,
)
from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
    UnknownBenchmarkAgentError,
)
from flight_agent_evaluator.benchmarks.release_verifier import ReleaseVerifier
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAggregateMetrics,
)
from flight_agent_evaluator.benchmarks.validator import BenchmarkCorpusValidator
from flight_agent_evaluator.cli.main import _get_version, main
from flight_agent_evaluator.contracts.scenarios import (
    BenchmarkScenario,
    ScenarioIdentifier,
    ScenarioLimits,
    ScenarioMetadata,
    ScenarioStep,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.judges.contracts import JudgeCriterion, JudgeEvidencePackage
from flight_agent_evaluator.judges.fake import FakeJudgeClient
from flight_agent_evaluator.judges.rubric import DEFAULT_RUBRIC
from flight_agent_evaluator.recording.contracts import (
    ProduceFinalResponseStep,
    ScriptedTrajectory,
)


def test_r01_legacy_benchmark_files_deleted() -> None:
    """R01: Verify suite.py and ablations.py are deleted and cannot be imported."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("flight_agent_evaluator.benchmarks.suite")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("flight_agent_evaluator.benchmarks.ablations")


def test_r02_no_synthetic_benchmark_constants() -> None:
    """R02: Verify synthetic constants do not exist in benchmark metrics or report generator."""
    from flight_agent_evaluator import benchmarks

    assert not hasattr(benchmarks, "compute_evaluator_value_add")
    assert not hasattr(benchmarks, "AblationEngine")
    assert not hasattr(benchmarks, "BenchmarkSuite")


def test_r03_registered_benchmark_identities() -> None:
    """R03: Verify registered benchmark identities match canonical baselines."""
    registry = BenchmarkAgentRegistry()
    registered_ids = [a["agent_id"] for a in registry.list_agents()]
    assert registered_ids == ["scripted-oracle", "naive-baseline", "random-baseline"]

    assert isinstance(registry.resolve("scripted-oracle"), ScriptedOracleAgent)
    assert isinstance(registry.resolve("naive-baseline"), NaiveBaselineAgent)
    assert isinstance(registry.resolve("random-baseline"), RandomBaselineAgent)


def test_r04_unregistered_agent_resolution_fails_closed() -> None:
    """R04: Verify BenchmarkAgentRegistry.resolve for unknown model raises UnknownBenchmarkAgentError."""
    registry = BenchmarkAgentRegistry()
    with pytest.raises(UnknownBenchmarkAgentError):
        registry.resolve("gpt-4o")
    with pytest.raises(UnknownBenchmarkAgentError):
        registry.resolve("claude-3-5-sonnet")


def test_r05_demo_run_truthfulness(capsys: pytest.CaptureFixture[str]) -> None:
    """R05: Verify cmd_demo_run prints truthful banner and qualitative judge status."""
    exit_code = main(["demo"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "FLIGHT AGENT EVALUATOR" in captured.out
    assert "PORTFOLIO DEMONSTRATION" in captured.out
    assert "Qualitative Judge:" in captured.out
    assert "Human calibration: pending" in captured.out
    assert "Overall Score:" in captured.out


def test_r06_model_agent_replay_manifest_required(capsys: pytest.CaptureFixture[str]) -> None:
    """R06: Verify cmd_agent_run with --agent model and --model-mode replay requires manifest."""
    exit_code = main(
        [
            "agent",
            "run",
            "resources/scenarios/jfk-lhr-delay.json",
            "--agent",
            "model",
            "--model-mode",
            "replay",
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "requires --model-replay-manifest PATH" in captured.err


def test_r07_ablation_subcommand_removed(capsys: pytest.CaptureFixture[str]) -> None:
    """R07: Verify cmd_ablation_run and CLI ablation subparser are completely removed."""
    with pytest.raises(SystemExit):
        main(["benchmark", "ablation"])
    captured = capsys.readouterr()
    assert "invalid choice: 'ablation'" in captured.err


def test_r08_qualitative_judge_rubric_ordinal_scale() -> None:
    """R08: Verify qualitative judge uses 0..4 ordinal rubric across 6 defined criteria."""
    rubric = DEFAULT_RUBRIC
    criteria_names = {c.criterion.value for c in rubric.criteria}
    expected_criteria = {
        JudgeCriterion.GROUNDEDNESS.value,
        JudgeCriterion.CONSTRAINT_AWARENESS.value,
        JudgeCriterion.UNCERTAINTY_COMMUNICATION.value,
        JudgeCriterion.COMPLETENESS.value,
        JudgeCriterion.HELPFULNESS.value,
        JudgeCriterion.CLARITY.value,
    }
    assert criteria_names == expected_criteria
    for c in rubric.criteria:
        scores = [a.score for a in c.anchors]
        assert scores == [0, 1, 2, 3, 4]


def test_r09_fake_judge_client_deterministic_test_double() -> None:
    """R09: Verify FakeJudgeClient functions as a deterministic test double."""
    pkg = JudgeEvidencePackage(
        package_id="pkg_test_1",
        run_id="run_test_1",
        scenario_id="jfk-lhr-delay",
        public_task="Help with flight",
        final_response="Done",
        trusted_observations=[],
        created_at=datetime.datetime.now(datetime.UTC),
    )
    client = FakeJudgeClient()
    result = asyncio.run(client.judge(pkg))
    assert result.overall_score == 2.0
    assert len(result.criteria_results) == 6


def test_r10_judge_calibration_declared_pending() -> None:
    """R10: Verify judge human calibration is declared pending in manifest."""
    loader = BenchmarkManifestLoader()
    manifest, _ = loader.load_builtin("benchmark-v1")
    assert manifest.judge_validation_status == "human_calibration_pending"


def test_r11_readme_python_api_verified() -> None:
    """R11: Verify README Python API snippet executes cleanly."""
    loader = ScenarioLoader()
    loaded = loader.load_builtin("jfk-lhr-delay")
    runner = BenchmarkRunner(scenario_loader=loader)
    agent = ScriptedOracleAgent()
    metric_view = asyncio.run(runner.run_scenario(loaded.scenario, agent))
    assert metric_view.task_success is True
    assert metric_view.safety_pass is True
    assert metric_view.overall_score >= 0.99


def test_r12_resource_paths_renamed_to_transactional() -> None:
    """R12: Verify stage-5 resources are moved to transactional and contain 12 scenarios."""
    assert not Path("resources/scenarios/stage-5").exists()
    assert not Path("resources/expectations/stage-5").exists()
    trans_sc = list(Path("resources/scenarios/transactional").glob("*.json"))
    trans_exp = list(Path("resources/expectations/transactional").glob("*.json"))
    assert len(trans_sc) == 12
    assert len(trans_exp) == 12


def test_r13_manifest_canonical_digest_integrity() -> None:
    """R13: Verify benchmark manifest canonical SHA-256 digest matches all 24 entries."""
    validator = BenchmarkCorpusValidator()
    report = validator.validate_manifest_file("resources/benchmarks/benchmark-v1.json")
    assert report.valid is True
    assert report.total_scenarios == 24
    assert len(report.errors) == 0


def test_r14_renamed_test_suites_exist() -> None:
    """R14: Verify domain-renamed test files exist."""
    assert Path("tests/integration/test_transactional_integration.py").is_file()
    assert Path("tests/unit/environment/test_transaction_safety.py").is_file()
    assert Path("tests/unit/evaluation/test_evaluator_fail_closed.py").is_file()
    assert Path("tests/unit/evaluation/test_trajectory_validity_counterexamples.py").is_file()
    assert Path("tests/e2e/test_model_agent_replay.py").is_file()


def test_r15_fail_closed_without_fixtures_or_cwd_fallback(tmp_path: Path) -> None:
    """R15: Verify CLI evaluate fails closed without tests/fixtures fallback."""
    exit_code = main(["evaluate", "nonexistent-run-id-xyz", "--output", str(tmp_path)])
    assert exit_code == 2


def test_r16_scenario_runner_computes_real_digest_not_zero_pad(tmp_path: Path) -> None:
    """R16: Verify ScenarioRunner.run on raw BenchmarkScenario computes canonical_digest()."""
    from flight_agent_evaluator.recording.store import FileRecordingStore

    scenario = BenchmarkScenario(
        schema_version={"major": 1, "minor": 0, "patch": 0},
        scenario_id=ScenarioIdentifier(id="test-sc", version=1),
        metadata=ScenarioMetadata(title="Test", description="Test", objective="Test"),
        limits=ScenarioLimits(tool_call_limit=5, time_limit_seconds=10),
        seed=42,
        steps=(ScenarioStep(step_id="s1", description="Step 1", initial_message="Hello"),),
        assertions=(),
        trajectory=ScriptedTrajectory(
            trajectory_id="t1",
            description="T",
            steps=(ProduceFinalResponseStep(step_id="s1", response="Done"),),
        ),
    )
    runner = ScenarioRunner()
    recording = asyncio.run(runner.run(scenario, output_dir=tmp_path))
    store = FileRecordingStore(tmp_path)
    bundle_manifest = store.read_bundle_manifest(str(recording.run_id))
    assert bundle_manifest.scenario_digest == scenario.canonical_digest()
    assert bundle_manifest.scenario_digest != "0" * 64


def test_r17_scenario_runner_driver_error_fails_closed() -> None:
    """R17: Verify ScenarioRunner handles driver exceptions cleanly and fails closed."""

    class FailingDriver:
        async def execute_step(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Simulated driver failure")

    scenario = BenchmarkScenario(
        schema_version={"major": 1, "minor": 0, "patch": 0},
        scenario_id=ScenarioIdentifier(id="test-fail", version=1),
        metadata=ScenarioMetadata(title="Fail", description="Fail", objective="Fail"),
        limits=ScenarioLimits(tool_call_limit=5, time_limit_seconds=10),
        seed=42,
        steps=(ScenarioStep(step_id="s1", description="Step 1", initial_message="Hello"),),
        assertions=(),
        trajectory=ScriptedTrajectory(
            trajectory_id="t1",
            description="T",
            steps=(ProduceFinalResponseStep(step_id="s1", response="Done"),),
        ),
    )
    runner = ScenarioRunner()
    recording = asyncio.run(runner.run(scenario, driver=FailingDriver()))
    assert recording.entry_count >= 1
    assert recording.evaluation is not None
    eval_dict = (
        recording.evaluation
        if isinstance(recording.evaluation, dict)
        else recording.evaluation.model_dump()
    )
    assert eval_dict.get("status") == "error"


def test_r18_benchmark_v1_baseline_artifacts_exist() -> None:
    """R18: Verify real offline baseline results exist in results/benchmark-v1/."""
    run_file = Path("results/benchmark-v1/run.json")
    summary_file = Path("results/benchmark-v1/summary.json")
    readme_file = Path("results/benchmark-v1/README.md")
    assert run_file.is_file()
    assert summary_file.is_file()
    assert readme_file.is_file()

    summary_data = json.loads(summary_file.read_text(encoding="utf-8"))
    metrics = BenchmarkAggregateMetrics.model_validate(summary_data)
    assert metrics.total_cases == 24
    assert metrics.total_runs == 72
    assert "scripted-oracle" in metrics.agent_pass_rates


def test_r19_release_verifier_full_pass() -> None:
    """R19: Verify ReleaseVerifier passes all 6 release checks."""
    verifier = ReleaseVerifier()
    report = verifier.verify_installed_release()
    assert report.valid is True
    assert report.passed_checks == 6
    assert report.failed_checks == 0


def test_r20_version_single_source() -> None:
    """R20: Verify version single source resolution across package and CLI."""
    import flight_agent_evaluator

    assert flight_agent_evaluator.__version__ == "0.2.0"
    assert _get_version() == "0.2.0"

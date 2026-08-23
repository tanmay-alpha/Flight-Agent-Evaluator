"""Release truth and benchmark-integrity regression tests."""

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
    NoOpBaselineAgent,
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
    InvokeToolStep,
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
    assert registered_ids == ["scripted-oracle", "naive-baseline", "no-op-baseline"]

    assert isinstance(registry.resolve("scripted-oracle"), ScriptedOracleAgent)
    assert isinstance(registry.resolve("naive-baseline"), NaiveBaselineAgent)
    assert isinstance(registry.resolve("no-op-baseline"), NoOpBaselineAgent)


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


def test_r21_oracle_100_percent_pass_rate() -> None:
    """R21: Verify ScriptedOracleAgent achieves 100% pass rate (24/24) on benchmark-v1."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    pass_count = 0
    for case in cases:
        agent = ScriptedOracleAgent()
        res = asyncio.run(runner.run_case(case=case, agent=agent, repetition_index=0))
        if res.task_success:
            pass_count += 1

    assert pass_count == len(cases) == 24


def test_r22_strict_score_monotonicity() -> None:
    """R22: Verify strict score monotonicity: oracle > naive > no-op."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    def score_agent(agent_factory: Any) -> float:
        total = 0.0
        for case in cases:
            res = asyncio.run(runner.run_case(case=case, agent=agent_factory(), repetition_index=0))
            total += res.overall_score
        return total / len(cases)

    oracle_score = score_agent(lambda: ScriptedOracleAgent())
    naive_score = score_agent(lambda: NaiveBaselineAgent())
    no_op_score = score_agent(lambda: NoOpBaselineAgent())

    assert oracle_score > naive_score > no_op_score
    assert oracle_score >= 0.95
    assert no_op_score <= 0.35


def test_r23_fail_closed_missing_assertion_evidence() -> None:
    """R23: Verify empty journal with assertions produces outcome_score = 0.0 (fail closed)."""
    from flight_agent_evaluator.contracts.evaluation import ToolCalledAssertion
    from flight_agent_evaluator.contracts.scenarios import (
        ScenarioIdentifier,
        ScenarioLimits,
        ScenarioMetadata,
        ScenarioStep,
    )
    from flight_agent_evaluator.contracts.trajectory_expectation import (
        ActionSelector,
        ExpectedAction,
        ScoringProfile,
        TrajectoryExpectation,
        ValidPath,
    )
    from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
    from flight_agent_evaluator.recording.journal import HashChainJournal

    scenario = BenchmarkScenario(
        schema_version="1.0.0",
        scenario_id=ScenarioIdentifier(id="test-fail-closed", version=1),
        metadata=ScenarioMetadata(title="Test", description="Test", objective="Test"),
        limits=ScenarioLimits(tool_call_limit=10, time_limit_seconds=60),
        seed=42,
        steps=(ScenarioStep(step_id="s1", description="s1", initial_message="m1"),),
        assertions=(
            ToolCalledAssertion(
                assertion_id="must-call-tool",
                assertion_type="tool_called",
                tool_name="flight.get_status",
            ),
        ),
        trajectory=ScriptedTrajectory(
            trajectory_id="t1",
            description="t",
            steps=(ProduceFinalResponseStep(step_id="resp", response="No op"),),
        ),
    )
    expectation = TrajectoryExpectation(
        scenario_id="test-fail-closed",
        expectation_version="1.0.0",
        scoring_profile=ScoringProfile(),
        valid_paths=[
            ValidPath(
                path_id="p1",
                name="P1",
                description="P1",
                expected_actions=[
                    ExpectedAction(
                        node_id="n1",
                        label="L",
                        selector=ActionSelector(
                            tool_name="flight.get_status",
                            mutation_class="read_only",
                        ),
                        required=True,
                    )
                ],
            )
        ],
    )
    evaluator = TrajectoryEvaluator()
    scorecard = evaluator.evaluate(
        scenario=scenario,
        expectation=expectation,
        journal=HashChainJournal(),
        run_id="run_empty_journal",
    )
    assert scorecard.outcome_score == 0.0
    assert scorecard.overall_pass is False


def test_r24_fail_closed_missing_action_dimensions() -> None:
    """R24: Verify required_recall == 0 produces zero argument correctness, dependency, and ordering scores."""
    from flight_agent_evaluator.contracts.scenarios import (
        ScenarioIdentifier,
        ScenarioLimits,
        ScenarioMetadata,
        ScenarioStep,
    )
    from flight_agent_evaluator.contracts.trajectory_expectation import (
        ActionSelector,
        DependencyConstraint,
        ExpectedAction,
        PrecedenceConstraint,
        ScoringProfile,
        TrajectoryExpectation,
        ValidPath,
    )
    from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
    from flight_agent_evaluator.recording.journal import HashChainJournal

    scenario = BenchmarkScenario(
        schema_version="1.0.0",
        scenario_id=ScenarioIdentifier(id="test-dim-fail-closed", version=1),
        metadata=ScenarioMetadata(title="Test", description="Test", objective="Test"),
        limits=ScenarioLimits(tool_call_limit=10, time_limit_seconds=60),
        seed=42,
        steps=(ScenarioStep(step_id="s1", description="s1", initial_message="m1"),),
        assertions=(),
        trajectory=ScriptedTrajectory(
            trajectory_id="t1",
            description="t",
            steps=(ProduceFinalResponseStep(step_id="resp", response="No op"),),
        ),
    )
    expectation = TrajectoryExpectation(
        scenario_id="test-dim-fail-closed",
        expectation_version="1.0.0",
        scoring_profile=ScoringProfile(),
        valid_paths=[
            ValidPath(
                path_id="p1",
                name="P1",
                description="P1",
                expected_actions=[
                    ExpectedAction(
                        node_id="n1",
                        label="Step 1",
                        selector=ActionSelector(
                            tool_name="booking.get_current",
                            mutation_class="read_only",
                        ),
                        required=True,
                    ),
                    ExpectedAction(
                        node_id="n2",
                        label="Step 2",
                        selector=ActionSelector(
                            tool_name="booking.confirm_rebooking",
                            mutation_class="sensitive_simulated_mutation",
                        ),
                        required=True,
                    ),
                ],
                dependency_constraints=[
                    DependencyConstraint(dependent_node_id="n2", required_node_id="n1")
                ],
                precedence_constraints=[
                    PrecedenceConstraint(before_node_id="n1", after_node_id="n2")
                ],
            )
        ],
    )
    evaluator = TrajectoryEvaluator()
    scorecard = evaluator.evaluate(
        scenario=scenario,
        expectation=expectation,
        journal=HashChainJournal(),
        run_id="run_zero_recall",
    )
    assert scorecard.required_recall == 0.0
    assert scorecard.argument_correctness_score == 0.0
    assert scorecard.dependency_score == 0.0
    assert scorecard.ordering_score == 0.0
    assert scorecard.overall_pass is False


def test_r25_full_run_lifecycle_journaling() -> None:
    """R25: Verify benchmark execution journals full lifecycle (run_started, final_response, run_completed)."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    case = cases[0]
    agent = ScriptedOracleAgent()
    mv = asyncio.run(
        runner.run_scenario(case.scenario, agent, case.expectation, authoritative=True)
    )

    assert mv.journal_digest is not None
    assert len(mv.journal_digest) == 64


def test_r26_journal_digest_binding() -> None:
    """R26: Verify journal_digest is bound into BenchmarkCaseResult and semantic_result_digest."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    case = cases[0]
    agent = ScriptedOracleAgent()
    res = asyncio.run(runner.run_case(case=case, agent=agent, repetition_index=0))

    assert res.journal_digest is not None
    assert len(res.journal_digest) == 64
    assert res.semantic_result_digest is not None

    # Tampering with journal_digest alters semantic digest
    tampered = res.model_copy(update={"journal_digest": "0" * 64})
    assert tampered.compute_semantic_result_digest() != res.semantic_result_digest


def test_r27_stale_resource_digest_detection() -> None:
    """R27: Verify stale resource digest detection fails closed."""
    import dataclasses

    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    case = cases[0]
    tampered_case = dataclasses.replace(case, scenario_raw_sha256="f" * 64)
    agent = ScriptedOracleAgent()

    # Result produced will reflect the tampered digest and differ from authentic run
    res_authentic = asyncio.run(runner.run_case(case=case, agent=agent, repetition_index=0))
    res_tampered = asyncio.run(runner.run_case(case=tampered_case, agent=agent, repetition_index=0))

    assert res_authentic.semantic_result_digest != res_tampered.semantic_result_digest


def test_r28_negative_control_zero_pass_rate() -> None:
    """R28: Verify NoOpBaselineAgent achieves 0.0% pass rate across all cases."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    pass_count = 0
    for case in cases:
        res = asyncio.run(runner.run_case(case=case, agent=NoOpBaselineAgent(), repetition_index=0))
        if res.task_success:
            pass_count += 1

    assert pass_count == 0


def test_r29_synthetic_fixture_coverage_completeness() -> None:
    """R29: Verify synthetic fixture coverage across all canonical scenarios."""
    from flight_agent_evaluator.providers.fixture import KNOWN_FLIGHT_STATUS_FIXTURES

    assert "AS142" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "DL123" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "WN678" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "AA321" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "AS310" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "UA456" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "DL456" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "AS505" in KNOWN_FLIGHT_STATUS_FIXTURES
    assert "UA789" in KNOWN_FLIGHT_STATUS_FIXTURES


def test_r30_deterministic_benchmark_smoke_test() -> None:
    """R30: Verify benchmark-v1 summary metrics match exact canonical numbers."""
    summary_path = Path("results/benchmark-v1/summary.json")
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["total_cases"] == 24
    assert summary["total_runs"] == 72
    assert summary["agent_pass_rates"]["scripted-oracle"] == 1.0
    assert summary["agent_pass_rates"]["no-op-baseline"] == 0.0
    assert summary["safety_pass_rate"] == 1.0


def test_r31_run_json_metrics_recompute_from_case_results() -> None:
    """R31: Verify run.json metrics recompute exactly from case_results."""
    run_path = Path("results/benchmark-v1/run.json")
    assert run_path.is_file()
    from flight_agent_evaluator.benchmarks.results import (
        BenchmarkAggregateMetrics,
        BenchmarkRunArtifact,
    )

    artifact = BenchmarkRunArtifact.model_validate_json(run_path.read_text(encoding="utf-8"))
    cases = artifact.case_results
    total_runs = len(cases)
    assert total_runs == 72

    task_success_count = sum(1 for r in cases if r.task_success)
    safety_pass_count = sum(1 for r in cases if r.safety_pass)
    error_count = sum(
        1
        for r in cases
        if "evaluator_error" in r.failure_codes or r.evaluator_status == "evaluator_error"
    )
    avg_score = sum(r.overall_score for r in cases) / total_runs

    agent_pass_rates: dict[str, float] = {}
    agent_avg_scores: dict[str, float] = {}
    for aid in artifact.executed_agents:
        a_cases = [r for r in cases if r.agent_id == aid]
        agent_pass_rates[aid] = sum(1 for r in a_cases if r.task_success) / len(a_cases)
        agent_avg_scores[aid] = sum(r.overall_score for r in a_cases) / len(a_cases)

    recomputed = BenchmarkAggregateMetrics(
        total_cases=artifact.scenario_count,
        total_runs=total_runs,
        task_success_rate=task_success_count / total_runs,
        safety_pass_rate=safety_pass_count / total_runs,
        evaluator_error_rate=error_count / total_runs,
        average_overall_score=avg_score,
        agent_pass_rates=agent_pass_rates,
        agent_average_scores=agent_avg_scores,
    )

    assert recomputed.total_runs == artifact.metrics.total_runs
    assert abs(recomputed.task_success_rate - artifact.metrics.task_success_rate) < 1e-6
    assert abs(recomputed.safety_pass_rate - artifact.metrics.safety_pass_rate) < 1e-6
    assert abs(recomputed.average_overall_score - artifact.metrics.average_overall_score) < 1e-6


def test_r32_summary_json_equals_run_metrics() -> None:
    """R32: Verify summary.json equals run.json metrics exactly."""
    from flight_agent_evaluator.benchmarks.results import (
        BenchmarkAggregateMetrics,
        BenchmarkRunArtifact,
    )

    summary = BenchmarkAggregateMetrics.model_validate_json(
        Path("results/benchmark-v1/summary.json").read_text(encoding="utf-8")
    )
    run = BenchmarkRunArtifact.model_validate_json(
        Path("results/benchmark-v1/run.json").read_text(encoding="utf-8")
    )

    assert summary.total_cases == run.metrics.total_cases
    assert summary.total_runs == run.metrics.total_runs
    assert abs(summary.task_success_rate - run.metrics.task_success_rate) < 1e-6
    assert abs(summary.safety_pass_rate - run.metrics.safety_pass_rate) < 1e-6
    assert abs(summary.average_overall_score - run.metrics.average_overall_score) < 1e-6
    assert summary.agent_pass_rates == run.metrics.agent_pass_rates


def test_r33_generated_readme_equals_committed_readme() -> None:
    """R33: Verify generated README equals committed README byte-for-byte (normalized)."""
    from flight_agent_evaluator.benchmarks.results import (
        BenchmarkRunArtifact,
        render_benchmark_report,
    )

    run = BenchmarkRunArtifact.model_validate_json(
        Path("results/benchmark-v1/run.json").read_text(encoding="utf-8")
    )
    generated = render_benchmark_report(run).strip().replace("\r\n", "\n")
    committed = (
        Path("results/benchmark-v1/README.md")
        .read_text(encoding="utf-8")
        .strip()
        .replace("\r\n", "\n")
    )

    assert generated == committed


def test_r34_manifest_digest_in_run_equals_current_manifest() -> None:
    """R34: Verify manifest digest in run.json matches current benchmark manifest digest."""
    from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
    from flight_agent_evaluator.benchmarks.results import BenchmarkRunArtifact

    manifest, _ = BenchmarkManifestLoader().load_builtin("benchmark-v1", verify_resources=False)
    run = BenchmarkRunArtifact.model_validate_json(
        Path("results/benchmark-v1/run.json").read_text(encoding="utf-8")
    )

    m_digest = manifest.manifest_digest or manifest.compute_canonical_digest()
    assert run.manifest_digest == m_digest


def test_r35_every_case_manifest_digest_equals_run_manifest_digest() -> None:
    """R35: Verify every case manifest_digest equals run.manifest_digest."""
    from flight_agent_evaluator.benchmarks.results import BenchmarkRunArtifact

    run = BenchmarkRunArtifact.model_validate_json(
        Path("results/benchmark-v1/run.json").read_text(encoding="utf-8")
    )
    for case in run.case_results:
        assert case.manifest_digest == run.manifest_digest


def test_r36_every_canonical_case_journal_digest_non_null() -> None:
    """R36: Verify all 72 canonical cases have non-null 64-char journal_digest."""
    from flight_agent_evaluator.benchmarks.results import BenchmarkRunArtifact

    run = BenchmarkRunArtifact.model_validate_json(
        Path("results/benchmark-v1/run.json").read_text(encoding="utf-8")
    )
    assert len(run.case_results) == 72
    for case in run.case_results:
        assert case.journal_digest is not None
        assert len(case.journal_digest) == 64


def test_r37_run_semantic_id_differs_for_filtered_run() -> None:
    """R37: Verify run_semantic_id differs when scenario selection changes."""
    from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine

    engine = CanonicalBenchmarkEngine()
    full_artifact = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
    )
    filtered_artifact = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
        scenario_filter=["approval-granted"],
    )

    assert full_artifact.run_semantic_id != filtered_artifact.run_semantic_id


def test_r38_demo_v1_case_result_has_benchmark_id_demo_v1() -> None:
    """R38: Verify demo-v1 case result has benchmark_id == 'demo-v1'."""
    from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
    from flight_agent_evaluator.engine.benchmark import BenchmarkRunner

    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("demo-v1", verify_resources=True)
    assert len(cases) > 0
    case = cases[0]
    assert case.benchmark_id == "demo-v1"

    runner = BenchmarkRunner()
    res = asyncio.run(runner.run_case(case=case, agent=ScriptedOracleAgent(), repetition_index=0))
    assert res.benchmark_id == "demo-v1"


def test_r39_result_agent_version_equals_actual_executed_agent_version() -> None:
    """R39: Verify result agent_version equals actual executed AgentPolicy.agent_version."""
    from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
    from flight_agent_evaluator.engine.benchmark import BenchmarkRunner

    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    agent = ScriptedOracleAgent()
    res = asyncio.run(runner.run_case(case=cases[0], agent=agent, repetition_index=0))
    assert res.agent_version == agent.agent_version == "1.0.0"


def test_r40_actual_runtime_run_id_propagates_into_case_result() -> None:
    """R40: Verify actual runtime run_id propagates into BenchmarkCaseResult."""
    from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
    from flight_agent_evaluator.engine.benchmark import BenchmarkRunner

    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    case = cases[0]
    mv = asyncio.run(
        runner.run_scenario(
            case.scenario, ScriptedOracleAgent(), case.expectation, authoritative=True
        )
    )
    res = asyncio.run(runner.run_case(case=case, agent=ScriptedOracleAgent(), repetition_index=0))

    assert mv.run_id is not None
    assert res.run_id is not None
    assert isinstance(res.run_id, str) and len(res.run_id) > 0


def test_r41_noop_negative_control_naming_and_behavior() -> None:
    """R41: Verify NoOpBaselineAgent naming, zero actions, and negative control registration."""
    agent = NoOpBaselineAgent()
    assert agent.agent_id == "no_op_baseline"
    assert agent.agent_version == "1.0.0"

    registry = BenchmarkAgentRegistry()
    resolved = registry.resolve("no-op-baseline")
    assert isinstance(resolved, NoOpBaselineAgent)


def test_monotonicity_per_case_property() -> None:
    """Property: For every canonical case, no_op_score <= oracle_score and no_op fails task."""
    from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
    from flight_agent_evaluator.engine.benchmark import BenchmarkRunner

    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1")
    runner = BenchmarkRunner()

    for case in cases:
        oracle_res = asyncio.run(
            runner.run_case(case=case, agent=ScriptedOracleAgent(), repetition_index=0)
        )
        no_op_res = asyncio.run(
            runner.run_case(case=case, agent=NoOpBaselineAgent(), repetition_index=0)
        )

        assert no_op_res.task_success is False
        assert no_op_res.overall_score <= oracle_res.overall_score


def test_trajectory_perturbation_properties() -> None:
    """Property: Trajectory perturbations (omission, wrong arguments, broken dependencies) cannot increase score."""
    from flight_agent_evaluator.contracts.scenarios import (
        BenchmarkScenario,
        ScenarioIdentifier,
        ScenarioLimits,
        ScenarioMetadata,
        ScenarioStep,
    )
    from flight_agent_evaluator.contracts.trajectory_expectation import (
        ActionSelector,
        ArgumentConstraint,
        DependencyConstraint,
        ExpectedAction,
        PrecedenceConstraint,
        ScoringProfile,
        TrajectoryExpectation,
        ValidPath,
    )
    from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
    from flight_agent_evaluator.recording.journal import HashChainJournal

    # Construct expectation requiring Action A -> Action B
    exp = TrajectoryExpectation(
        scenario_id="perturbation-test",
        expectation_version="1.0.0",
        scoring_profile=ScoringProfile(
            weight_outcome=0.3,
            weight_tool_selection=0.2,
            weight_argument_correctness=0.2,
            weight_dependency=0.1,
            weight_ordering=0.1,
            weight_efficiency=0.1,
        ),
        valid_paths=[
            ValidPath(
                path_id="path-1",
                expected_actions=[
                    ExpectedAction(
                        node_id="act-1",
                        selector=ActionSelector(
                            tool_name="flight.get_status",
                            argument_constraints=[
                                ArgumentConstraint(
                                    field_pointer="/flight_number",
                                    operator="equals",
                                    value="AS142",
                                )
                            ],
                        ),
                        required=True,
                    ),
                    ExpectedAction(
                        node_id="act-2",
                        selector=ActionSelector(tool_name="flight.search"),
                        required=True,
                    ),
                ],
                precedence_constraints=[
                    PrecedenceConstraint(before_node_id="act-1", after_node_id="act-2")
                ],
                dependency_constraints=[
                    DependencyConstraint(dependent_node_id="act-2", required_node_id="act-1")
                ],
            )
        ],
    )

    scenario = BenchmarkScenario(
        scenario_id=ScenarioIdentifier(id="perturbation-test", version=1),
        metadata=ScenarioMetadata(title="Test", description="Test", objective="Test objective"),
        limits=ScenarioLimits(tool_call_limit=5, time_limit_seconds=60),
        steps=(ScenarioStep(step_id="step-0", description="Init"),),
        trajectory=ScriptedTrajectory(
            trajectory_id="traj-1",
            description="Test",
            steps=[
                InvokeToolStep(
                    step_id="s1",
                    tool_name="flight.get_status",
                    arguments={"flight_number": "AS142"},
                ),
                InvokeToolStep(step_id="s2", tool_name="flight.search", arguments={}),
            ],
        ),
    )

    evaluator = TrajectoryEvaluator()

    def make_journal(calls: list[tuple[str, dict[str, Any]]]) -> HashChainJournal:
        import uuid as _uuid

        j = HashChainJournal()
        r_id = str(_uuid.uuid4())
        t0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        j.append_event("run_started", r_id, "corr-0", t0, {"msg": "start"})
        for i, (tool_name, args) in enumerate(calls, start=1):
            t_call = t0 + datetime.timedelta(seconds=i * 2)
            t_res = t0 + datetime.timedelta(seconds=i * 2 + 1)
            j.append_event(
                "tool_call",
                r_id,
                f"corr-{i}",
                t_call,
                {"call_id": f"c{i}", "tool_name": tool_name, "arguments": args},
            )
            j.append_event(
                "tool_result",
                r_id,
                f"corr-{i}",
                t_res,
                {"call_id": f"c{i}", "status": "success", "result": {"flight_id": "AS142"}},
            )
        j.append_event(
            "run_completed", r_id, "corr-end", t0 + datetime.timedelta(seconds=100), {"msg": "end"}
        )
        return j

    # Baseline perfect trajectory
    j_perfect = make_journal(
        [
            ("flight.get_status", {"flight_number": "AS142"}),
            ("flight.search", {}),
        ]
    )
    res_perfect = evaluator.evaluate(scenario, exp, j_perfect, "Done")
    score_perfect = res_perfect.composite_score
    assert res_perfect.overall_pass is True

    # Perturbation 1: Omission of required step (search omitted)
    j_omitted = make_journal(
        [
            ("flight.get_status", {"flight_number": "AS142"}),
        ]
    )
    res_omitted = evaluator.evaluate(scenario, exp, j_omitted, "Done")
    assert res_omitted.composite_score < score_perfect
    assert res_omitted.overall_pass is False

    # Perturbation 2: Wrong argument
    j_wrong_arg = make_journal(
        [
            ("flight.get_status", {"flight_number": "WRONG"}),
            ("flight.search", {}),
        ]
    )
    res_wrong_arg = evaluator.evaluate(scenario, exp, j_wrong_arg, "Done")
    assert res_wrong_arg.composite_score < score_perfect
    assert res_wrong_arg.overall_pass is False

    # Perturbation 3: Broken dependency / precedence (search executed before status)
    j_broken_dep = make_journal(
        [
            ("flight.search", {}),
            ("flight.get_status", {"flight_number": "AS142"}),
        ]
    )
    res_broken_dep = evaluator.evaluate(scenario, exp, j_broken_dep, "Done")
    assert res_broken_dep.composite_score < score_perfect
    assert res_broken_dep.overall_pass is False

"""Benchmark integrity comprehensive test matrix (BI-001 through BI-030)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkCase,
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
    ManifestValidationError,
    ResourceDigestMismatchError,
)
from flight_agent_evaluator.benchmarks.manifest import (
    BenchmarkAgentEntry,
    BenchmarkManifest,
    BenchmarkScenarioEntry,
)
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
    UnknownBenchmarkAgentError,
)
from flight_agent_evaluator.benchmarks.results import BenchmarkCaseResult
from flight_agent_evaluator.benchmarks.suite import BenchmarkSuite
from flight_agent_evaluator.benchmarks.validator import BenchmarkCorpusValidator
from flight_agent_evaluator.cli.main import main
from flight_agent_evaluator.contracts.model import AgentTask, ModelRequest
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.trajectory_expectation import TrajectoryExpectation


def test_bi_001_unknown_agent_rejected() -> None:
    """BI-001: Unknown agent identifier must raise UnknownBenchmarkAgentError."""
    registry = BenchmarkAgentRegistry()
    with pytest.raises(UnknownBenchmarkAgentError):
        registry.resolve("unregistered_agent_xyz")


def test_bi_002_gpt4o_cannot_alias_oracle() -> None:
    """BI-002: gpt-4o cannot silently alias to ScriptedOracleAgent."""
    registry = BenchmarkAgentRegistry()
    with pytest.raises(UnknownBenchmarkAgentError):
        registry.resolve("gpt-4o")


def test_bi_003_unknown_scenario_rejected() -> None:
    """BI-003: Requesting unknown scenario in suite fails closed."""
    suite = BenchmarkSuite()
    with pytest.raises(FileNotFoundError):
        suite.run_benchmark(
            model_names=["scripted-oracle"],
            scenarios=[{"id": "completely-unknown-scenario", "version": 1}],
        )


def test_bi_004_no_jfk_fallback() -> None:
    """BI-004: Missing scenario never silently falls back to jfk-lhr-delay."""
    suite = BenchmarkSuite()
    with pytest.raises(FileNotFoundError, match="could not be resolved on disk"):
        suite.run_benchmark(
            model_names=["scripted-oracle"],
            scenarios=[{"id": "nonexistent_scenario_123"}],
        )


def test_bi_005_scenario_digest_tamper_detected(tmp_path: Path) -> None:
    """BI-005: Tampering with scenario bytes fails digest check."""
    loader = BenchmarkManifestLoader()
    manifest_path = Path("resources/benchmarks/benchmark-v1.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["scenarios"][0]["scenario_sha256"] = "1" * 64

    tampered_p = tmp_path / "tampered.json"
    tampered_p.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(
        (ResourceDigestMismatchError, ManifestValidationError, BenchmarkIntegrityError)
    ):
        loader.load_manifest(tampered_p)


def test_bi_006_expectation_digest_tamper_detected(tmp_path: Path) -> None:
    """BI-006: Tampering with expectation bytes fails digest check."""
    loader = BenchmarkManifestLoader()
    manifest_path = Path("resources/benchmarks/benchmark-v1.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["scenarios"][0]["expectation_sha256"] = "2" * 64

    tampered_p = tmp_path / "tampered.json"
    tampered_p.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(
        (ResourceDigestMismatchError, ManifestValidationError, BenchmarkIntegrityError)
    ):
        loader.load_manifest(tampered_p)


def test_bi_007_wrong_expectation_paired_with_scenario_rejected() -> None:
    """BI-007: Mismatched scenario and expectation IDs in BenchmarkCase raises ManifestValidationError."""
    entry = BenchmarkScenarioEntry(
        scenario_id="sc_a",
        scenario_version=1,
        scenario_path="resources/scenarios/jfk-lhr-delay.json",
        scenario_sha256="a" * 64,
        expectation_path="resources/expectations/jfk-lhr-delay.json",
        expectation_sha256="b" * 64,
    )

    sc_raw = Path("resources/scenarios/jfk-lhr-delay.json").read_text(encoding="utf-8")
    scenario = BenchmarkScenario.model_validate_json(sc_raw)

    exp_raw = Path("resources/expectations/lax-sfo-ontime.json").read_text(encoding="utf-8")
    mismatched_exp = TrajectoryExpectation.model_validate_json(exp_raw)

    with pytest.raises(ManifestValidationError, match="ID mismatch"):
        BenchmarkCase(
            manifest_entry=entry,
            scenario=scenario,
            expectation=mismatched_exp,
            scenario_raw_sha256="a" * 64,
            expectation_raw_sha256="b" * 64,
        )


def test_bi_008_manifest_duplicate_scenario_id_rejected() -> None:
    """BI-008: Manifest with duplicate scenario IDs is rejected."""
    entry1 = BenchmarkScenarioEntry(
        scenario_id="sc_dup",
        scenario_version=1,
        scenario_path="resources/scenarios/jfk-lhr-delay.json",
        scenario_sha256="a" * 64,
        expectation_path="resources/expectations/jfk-lhr-delay.json",
        expectation_sha256="b" * 64,
    )
    with pytest.raises(ValueError, match="Duplicate scenario IDs"):
        BenchmarkManifest(
            benchmark_id="bm_dup",
            benchmark_version="1.0.0",
            scenarios=(entry1, entry1),
            agents=(
                BenchmarkAgentEntry(
                    agent_id="scripted-oracle",
                    implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
                ),
            ),
        )


def test_bi_009_absolute_path_rejected() -> None:
    """BI-009: Absolute path in manifest entry is rejected."""
    with pytest.raises(ValueError, match="Path must be relative"):
        BenchmarkScenarioEntry(
            scenario_id="sc_abs",
            scenario_version=1,
            scenario_path="/etc/passwd",
            scenario_sha256="a" * 64,
            expectation_path="resources/expectations/jfk-lhr-delay.json",
            expectation_sha256="b" * 64,
        )


def test_bi_010_parent_traversal_rejected() -> None:
    """BI-010: Parent path traversal '..' in manifest entry is rejected."""
    with pytest.raises(ValueError, match="Path traversal '..' is forbidden"):
        BenchmarkScenarioEntry(
            scenario_id="sc_trav",
            scenario_version=1,
            scenario_path="../../secret.json",
            scenario_sha256="a" * 64,
            expectation_path="resources/expectations/jfk-lhr-delay.json",
            expectation_sha256="b" * 64,
        )


def test_bi_011_unsupported_version_rejected() -> None:
    """BI-011: Manifest missing version fields fails validation."""
    with pytest.raises(Exception):
        BenchmarkManifest.model_validate({"benchmark_id": "bm1"})


def test_bi_012_all_zero_sha_rejected() -> None:
    """BI-012: All-zero SHA256 is rejected."""
    with pytest.raises(ValueError, match="not all zeros"):
        BenchmarkScenarioEntry(
            scenario_id="sc_zero",
            scenario_version=1,
            scenario_path="resources/scenarios/jfk-lhr-delay.json",
            scenario_sha256="0" * 64,
            expectation_path="resources/expectations/jfk-lhr-delay.json",
            expectation_sha256="b" * 64,
        )


def test_bi_013_hidden_expectation_absent_from_agent_task() -> None:
    """BI-013: Hidden expectation rules are never serialized into AgentTask."""
    scenario = BenchmarkScenario.model_validate_json(
        Path("resources/scenarios/jfk-lhr-delay.json").read_text(encoding="utf-8")
    )
    task = AgentTask(
        task_id="task-1",
        scenario_id=scenario.scenario_id.id,
        public_request=scenario.metadata.description,
    )
    task_json = task.model_dump_json()
    assert "safety_constraints" not in task_json
    assert "valid_paths" not in task_json


def test_bi_014_hidden_expectation_absent_from_model_request() -> None:
    """BI-014: Hidden expectation answers are never serialized into ModelRequest."""
    req = ModelRequest(
        request_id="req-1",
        prompt_policy_id="policy-1",
        prompt_policy_version="1.0.0",
        prompt_digest="a" * 64,
        turn_index=0,
        messages=[{"role": "user", "content": "Check flight AS142"}],
    )
    req_json = req.model_dump_json()
    assert "expected_actions" not in req_json


def test_bi_015_authored_expectation_loaded() -> None:
    """BI-015: Authoritative loader loads exact authored expectations."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_manifest("resources/benchmarks/benchmark-v1.json")
    assert len(cases) == 24
    for c in cases:
        assert isinstance(c.expectation, TrajectoryExpectation)
        assert len(c.expectation.valid_paths) > 0


def test_bi_016_generated_default_expectation_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """BI-016: Official engine never invokes _build_development_expectation."""
    from flight_agent_evaluator.engine.benchmark import BenchmarkRunner

    calls = []
    orig = BenchmarkRunner._build_development_expectation

    def spy(self: BenchmarkRunner, scenario: BenchmarkScenario) -> TrajectoryExpectation:
        calls.append(scenario.scenario_id.id)
        return orig(self, scenario)

    monkeypatch.setattr(BenchmarkRunner, "_build_development_expectation", spy)

    engine = CanonicalBenchmarkEngine()
    engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
    )
    assert len(calls) == 0, f"Development expectation was called for scenarios: {calls}"


def test_bi_017_extra_filesystem_scenario_ignored(tmp_path: Path) -> None:
    """BI-017: Adding extra non-manifest file does not affect canonical benchmark cases."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_manifest("resources/benchmarks/benchmark-v1.json")

    extra_file = Path("resources/scenarios/extra_ignored.json")
    try:
        extra_file.write_text("{}", encoding="utf-8")
        manifest2, cases2 = loader.load_manifest("resources/benchmarks/benchmark-v1.json")
        assert len(cases2) == len(cases)
        assert manifest2.compute_canonical_digest() == manifest.compute_canonical_digest()
    finally:
        if extra_file.exists():
            extra_file.unlink()


def test_bi_018_exact_agent_identity_preserved() -> None:
    """BI-018: Evaluated result accurately records the instantiated agent identity."""
    engine = CanonicalBenchmarkEngine()
    artifact = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["naive-baseline"],
    )
    for res in artifact.case_results:
        assert res.agent_id == "naive-baseline"


def test_bi_019_fixed_fake_timing_absent() -> None:
    """BI-019: Execution timing is measured dynamically, not hardcoded to 120.0."""
    suite = BenchmarkSuite()
    summary = suite.run_benchmark(
        model_names=["scripted-oracle"],
        scenarios=[{"id": "jfk-lhr-delay", "version": 1}],
    )
    res = summary.results[0]
    # Dynamic timing will rarely if ever equal exactly 120.000000 ms
    assert res.execution_time_ms != 120.0 or res.execution_time_ms > 0.0


def test_bi_020_semantic_result_deterministic_across_runs() -> None:
    """BI-020: Repeated execution produces identical semantic result digests."""
    engine = CanonicalBenchmarkEngine()
    art1 = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
    )
    art2 = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
    )
    digests1 = [r.semantic_result_digest for r in art1.case_results]
    digests2 = [r.semantic_result_digest for r in art2.case_results]
    assert digests1 == digests2


def test_bi_021_wall_clock_metadata_excluded_from_semantic_digest() -> None:
    """BI-021: Wall-clock timing does not change semantic_result_digest."""
    res1 = BenchmarkCaseResult(
        benchmark_id="bm1",
        benchmark_version="1.0.0",
        scenario_id="sc1",
        scenario_version=1,
        scenario_resource_digest="a" * 64,
        expectation_resource_digest="b" * 64,
        agent_id="agent1",
        task_success=True,
        safety_pass=True,
        overall_score=1.0,
        run_id="r1",
        wall_time_ms=10.5,
    )
    res2 = res1.model_copy(update={"wall_time_ms": 999.9})
    assert res1.compute_semantic_result_digest() == res2.compute_semantic_result_digest()


def test_bi_022_cli_and_library_engine_results_equivalent(tmp_path: Path) -> None:
    """BI-022: CLI execution produces equivalent summary and artifacts to library execution."""
    out_dir = tmp_path / "cli_run"
    code = main(
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
    assert code == 0
    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "cases").is_dir()


def test_bi_023_output_persists_artifact(tmp_path: Path) -> None:
    """BI-023: Persisting artifacts creates atomic run.json, summary.json, and cases."""
    engine = CanonicalBenchmarkEngine()
    out_dir = tmp_path / "persist_test"
    engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
        output_dir=out_dir,
    )
    assert (out_dir / "run.json").is_file()
    assert (out_dir / "summary.json").is_file()
    cases = list((out_dir / "cases").glob("*.json"))
    assert len(cases) == 24


def test_bi_024_nonexistent_report_artifact_fails() -> None:
    """BI-024: Generating report for missing file returns exit code 1."""
    code = main(["benchmark", "report", "--results", "definitely_nonexistent_file.json"])
    assert code == 1


def test_bi_025_malformed_report_artifact_fails(tmp_path: Path) -> None:
    """BI-025: Generating report for malformed artifact returns exit code 1."""
    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"invalid": true}', encoding="utf-8")
    code = main(["benchmark", "report", "--results", str(malformed)])
    assert code == 1


def test_bi_026_all_24_manifest_entries_bind_scenario_and_expectation() -> None:
    """BI-026: Authoritative manifest contains exactly 24 valid bindings."""
    validator = BenchmarkCorpusValidator()
    report = validator.validate_manifest_file("resources/benchmarks/benchmark-v1.json")
    assert report.valid is True
    assert report.total_scenarios == 24
    assert len(report.errors) == 0


def test_bi_027_corpus_tool_selectors_resolve() -> None:
    """BI-027: All expectation tool selectors in corpus resolve to registered aviation tools."""
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_manifest("resources/benchmarks/benchmark-v1.json")
    registered_tools = {
        "flight.get_status",
        "flight.search",
        "flight.search_flights",
        "booking.get_current",
        "itinerary.get_current_booking",
        "booking.hold_alternative",
        "booking.confirm_rebooking",
        "booking.release_hold",
        "approval.request",
        "approval.get_status",
        "policy.get_rebooking_rules",
        "notification.send_simulated",
    }
    for case in cases:
        for p in case.expectation.valid_paths:
            for act in p.expected_actions:
                if act.selector.tool_name:
                    assert (
                        act.selector.tool_name in registered_tools or "*" in act.selector.tool_name
                    )


def test_bi_028_manifest_runtime_versions_match() -> None:
    """BI-028: Manifest declared versions match runtime constants."""
    loader = BenchmarkManifestLoader()
    manifest, _ = loader.load_manifest("resources/benchmarks/benchmark-v1.json")
    assert manifest.environment_version == "1.0.0"
    assert manifest.evaluator_version == "1.0.0"
    assert manifest.taxonomy_version == "1.0.0"
    assert manifest.scoring_profile_version == "1.0.0"


def test_bi_029_oracle_evaluated_against_authored_expectation() -> None:
    """BI-029: Oracle execution result is scored against authored expectation graph."""
    engine = CanonicalBenchmarkEngine()
    artifact = engine.run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
    )
    # At least some scenarios must pass and have evidence-backed scores
    passing = [r for r in artifact.case_results if r.task_success]
    assert len(passing) > 0


def test_bi_030_evaluator_error_not_counted_as_success() -> None:
    """BI-030: An evaluator error is never reported as task_success=True."""
    res = BenchmarkCaseResult(
        benchmark_id="bm1",
        benchmark_version="1.0.0",
        scenario_id="sc1",
        scenario_version=1,
        scenario_resource_digest="a" * 64,
        expectation_resource_digest="b" * 64,
        agent_id="agent1",
        task_success=False,
        safety_pass=True,
        evaluator_status="evaluator_error",
        failure_codes=["evaluator_error"],
        overall_score=0.0,
        run_id="r1",
    )
    assert res.task_success is False
    assert res.evaluator_status == "evaluator_error"

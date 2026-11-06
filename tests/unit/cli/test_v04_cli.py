"""Consumer-visible CLI gates, real-bundle comparison and SDK regressions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from flight_agent_evaluator.benchmarks.compare import compare_runs
from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
from flight_agent_evaluator.benchmarks.results import BenchmarkRunArtifact
from flight_agent_evaluator.cli.main import main
from flight_agent_evaluator.engine.benchmark import BenchmarkMetricVector


@pytest.fixture(scope="module")
def artifact() -> BenchmarkRunArtifact:
    return CanonicalBenchmarkEngine().run_benchmark(
        agent_ids=["scripted-oracle"], scenario_filter=["jfk-lhr-delay"], repetitions=1
    )


def bundle(path: Path, artifact: BenchmarkRunArtifact) -> Path:
    artifact.persist_verified_bundle(path)
    return path / "run.json"


def changed(
    artifact: BenchmarkRunArtifact, *, success: bool, safety: bool = True
) -> BenchmarkRunArtifact:
    case = artifact.case_results[0].model_copy(
        update={
            "task_success": success,
            "safety_pass": safety,
            "overall_score": float(success),
            "failure_codes": [] if success and safety else ["TASK_TEST_FAILURE"],
        }
    )
    case = case.model_copy(update={"semantic_result_digest": case.compute_semantic_result_digest()})
    metrics = artifact.metrics.model_copy(
        update={
            "task_success_rate": float(success),
            "safety_pass_rate": float(safety),
            "average_overall_score": float(success),
        }
    )
    return artifact.model_copy(update={"case_results": [case], "metrics": metrics})


def test_compare_real_tmp_bundles(artifact, tmp_path, capsys):
    before = bundle(tmp_path / "before", changed(artifact, success=True))
    after = bundle(tmp_path / "after", changed(artifact, success=False))
    assert main(["benchmark", "compare", str(before), str(after), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["task_success_delta"] == -1
    assert data["per_agent"][0]["task_success_delta"] == -1
    assert data["per_scenario"][0]["overall_score_delta"] == -1
    assert data["newly_failing"][0]["candidate_codes"] == ["TASK_TEST_FAILURE"]
    report = compare_runs(before, after)
    assert report.render_json() == compare_runs(before, after).render_json()
    assert main(["benchmark", "compare", str(before), str(after)]) == 0
    printed = capsys.readouterr().out
    assert printed == report.render_markdown()
    assert "## Per agent" in printed and "TASK_TEST_FAILURE" in printed
    reverse = compare_runs(after, before)
    assert reverse.newly_passing[0].baseline_codes == ["TASK_TEST_FAILURE"]


def test_compare_manifest_mismatch(artifact, tmp_path, capsys):
    a = bundle(tmp_path / "a", artifact)
    other = artifact.model_copy(update={"manifest_digest": "different"})
    b = tmp_path / "b.json"
    b.write_text(other.model_dump_json(), encoding="utf-8")
    assert main(["benchmark", "compare", str(a), str(b)]) == 2
    assert "Manifest mismatch" in capsys.readouterr().err
    assert (
        main(["benchmark", "compare", str(a), str(b), "--allow-manifest-mismatch", "--json"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["manifest_matches"] is False


def test_compare_unmatched_and_duplicate_cases(artifact):
    case = artifact.case_results[0]
    extra = case.model_copy(update={"repetition_index": case.repetition_index + 1})
    candidate = artifact.model_copy(update={"case_results": [extra]})
    report = compare_runs(artifact, candidate)
    assert len(report.added_cases) == len(report.removed_cases) == 1
    assert not report.newly_failing and not report.newly_passing
    with pytest.raises(ValueError, match="duplicate"):
        compare_runs(artifact, artifact.model_copy(update={"case_results": [case, case]}))
    one_sided = case.model_copy(update={"agent_id": "another", "scenario_id": "another"})
    report = compare_runs(artifact, artifact.model_copy(update={"case_results": [one_sided]}))
    assert all(group.task_success_delta is None for group in report.per_agent)


@pytest.mark.parametrize(
    ("flags", "success", "safety", "error_rate", "expected"),
    [
        ([], True, True, 0, 0),
        (["--fail-under-success", "1"], False, True, 0, 1),
        (["--fail-under-success", "0"], False, True, 0, 0),
        (["--require-safety"], True, False, 0, 1),
        (["--require-safety"], True, True, 0, 0),
        ([], False, False, 1, 3),
    ],
)
def test_benchmark_gate_exit_codes(artifact, capsys, flags, success, safety, error_rate, expected):
    result = changed(artifact, success=success, safety=safety)
    result = result.model_copy(
        update={"metrics": result.metrics.model_copy(update={"evaluator_error_rate": error_rate})}
    )
    with patch.object(CanonicalBenchmarkEngine, "run_benchmark", return_value=result):
        assert main(["benchmark", "run", *flags, "--json"]) == expected
    assert "task_success_rate" in json.loads(capsys.readouterr().out)["metrics"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--fail-under-success", "1.1"],
        ["--fail-under-success", "nan"],
        ["--max-regression", "0.1"],
        ["--baseline", "missing.json"],
        ["--baseline", "missing.json", "--max-regression", "-0.1"],
    ],
)
def test_bad_gate_inputs_do_not_execute(flags, capsys):
    with patch.object(CanonicalBenchmarkEngine, "run_benchmark") as run:
        assert main(["benchmark", "run", *flags]) == 2
        run.assert_not_called()
    assert "Error" in capsys.readouterr().err


def test_baseline_regression_gate(artifact, tmp_path, capsys):
    baseline = bundle(tmp_path / "base", changed(artifact, success=True))
    candidate = changed(artifact, success=False)
    with patch.object(CanonicalBenchmarkEngine, "run_benchmark", return_value=candidate):
        assert (
            main(
                [
                    "benchmark",
                    "run",
                    "--baseline",
                    str(baseline),
                    "--max-regression",
                    "0.2",
                    "--json",
                ]
            )
            == 1
        )
        capsys.readouterr()
        assert (
            main(
                ["benchmark", "run", "--baseline", str(baseline), "--max-regression", "1", "--json"]
            )
            == 0
        )


def test_benchmark_errors_have_separate_exit_codes(capsys):
    for exception, expected in (
        (ValueError("bad input"), 2),
        (RuntimeError("evaluator failed"), 3),
    ):
        with patch.object(CanonicalBenchmarkEngine, "run_benchmark", side_effect=exception):
            assert main(["benchmark", "run"]) == expected
        assert "error" in capsys.readouterr().err.lower()


def test_benchmark_list_broken_manifest_is_error(capsys):
    with patch(
        "flight_agent_evaluator.benchmarks.loader.BenchmarkManifestLoader.load_builtin",
        side_effect=ValueError("broken"),
    ):
        assert main(["benchmark", "list", "--json"]) == 2
    captured = capsys.readouterr()
    assert "broken benchmark manifest" in captured.err
    assert json.loads(captured.out)


@pytest.mark.parametrize(
    "command",
    [
        ["verify", "missing"],
        ["evaluate", "missing"],
        ["evaluator", "validate", "--output", "unused"],
    ],
)
def test_json_after_previously_missing_subcommands(command, capsys):
    target = "cmd_" + ("evaluator_validate" if command[0] == "evaluator" else command[0])
    with patch(f"flight_agent_evaluator.cli.main.{target}", return_value=0) as handler:
        assert main([*command, "--json"]) == 0
        assert handler.call_args.args[0].json is True


@pytest.mark.parametrize("command", ["run", "validate"])
def test_dead_scenarios_alias_is_rejected(command, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["benchmark", command, "--scenarios", "resources/scenarios"])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_agent_expectation_flags_are_forwarded(capsys):
    metric = BenchmarkMetricVector(
        scenario_id="jfk-lhr-delay", agent_id="oracle", task_success=True, safety_pass=True
    )
    with patch(
        "flight_agent_evaluator.cli.main.BenchmarkRunner.run_scenario", return_value=metric
    ) as run:
        assert (
            main(
                [
                    "agent",
                    "run",
                    "resources/scenarios/jfk-lhr-delay.json",
                    "--expectation",
                    "resources/expectations/jfk-lhr-delay.json",
                    "--allow-development-expectation",
                    "--json",
                ]
            )
            == 0
        )
    kwargs = run.call_args.kwargs
    assert kwargs["expectation"].scenario_id == "jfk-lhr-delay"
    assert kwargs["allow_development_expectation"] is True
    assert json.loads(capsys.readouterr().out)["task_success"] is True


def test_missing_authored_expectation_is_clear_error(tmp_path, capsys):
    source = Path("resources/scenarios/jfk-lhr-delay.json")
    data: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    data["scenario_id"]["id"] = "unpublished-example"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(data), encoding="utf-8")
    assert main(["agent", "run", str(scenario)]) == 2
    assert "--expectation PATH" in capsys.readouterr().err
    assert main(["agent", "run", str(scenario), "--allow-development-expectation", "--json"]) in (
        0,
        1,
    )
    assert "task_success" in json.loads(capsys.readouterr().out)


def test_agent_errors_are_not_task_failures(capsys):
    with patch(
        "flight_agent_evaluator.cli.main.BenchmarkRunner.run_scenario",
        side_effect=RuntimeError("failed"),
    ):
        assert main(["agent", "run", "resources/scenarios/jfk-lhr-delay.json"]) == 3
    assert "Execution error" in capsys.readouterr().err
    assert main(["agent", "run", "missing.json"]) == 2


def test_report_json_flag_outputs_json(artifact, tmp_path, capsys):
    path = bundle(tmp_path / "bundle", artifact)
    assert main(["benchmark", "report", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run_semantic_id"] == artifact.run_semantic_id


def test_failure_details_are_printed_with_evidence_and_remediation(artifact, tmp_path, capsys):
    detail = {
        "code": "TASK_TEST_FAILURE",
        "severity": "error",
        "message": "Required action missing",
        "evidence_sequences": [2, 4],
        "remediation": "Execute the required lookup",
    }
    data = artifact.model_dump(mode="json")
    data["case_results"][0]["failure_details"] = [detail]
    result = BenchmarkRunArtifact.model_validate(data)
    with patch.object(CanonicalBenchmarkEngine, "run_benchmark", return_value=result):
        assert main(["benchmark", "run"]) == 0
    output = capsys.readouterr().out
    assert "Required action missing" in output
    assert "Evidence sequences: [2, 4]" in output
    assert "Remediation: Execute the required lookup" in output
    path = tmp_path / "run.json"
    path.write_text(result.model_dump_json(), encoding="utf-8")
    assert main(["benchmark", "report", str(path)]) == 0
    assert "Required action missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("success", "error", "expected"),
    [(False, None, 1), (True, None, 0), (False, "failed scoring", 3)],
)
def test_agent_run_status_exit_codes(success, error, expected, capsys):
    metric = BenchmarkMetricVector(
        scenario_id="jfk-lhr-delay",
        agent_id="oracle",
        task_success=success,
        safety_pass=True,
        evaluator_error=error,
    )
    with patch("flight_agent_evaluator.cli.main.BenchmarkRunner.run_scenario", return_value=metric):
        assert (
            main(["agent", "run", "resources/scenarios/jfk-lhr-delay.json", "--json"]) == expected
        )
    assert json.loads(capsys.readouterr().out)["task_success"] is success


def test_compare_rejects_non_strict_json(tmp_path, capsys):
    path = tmp_path / "run.json"
    path.write_text('{"manifest_digest":"first","manifest_digest":"second"}', encoding="utf-8")
    assert main(["benchmark", "compare", str(path), str(path), "--json"]) == 2
    assert "duplicate key" in capsys.readouterr().err


def test_annotation_workflow_rejects_malformed_annotations_through_main_cli(tmp_path, capsys):
    bad = tmp_path / "annotator.jsonl"
    bad.write_text('{"annotator_id": "a", "annotator_id": "b"}\n', encoding="utf-8")
    code = main(["annotation", "workflow", "--", "validate", str(bad)])
    captured = capsys.readouterr()
    assert code != 0
    assert "duplicate key" in (captured.out + captured.err)

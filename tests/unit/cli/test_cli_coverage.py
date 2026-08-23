"""Comprehensive unit tests for CLI subcommands and coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from flight_agent_evaluator.cli.main import (
    _get_version,
    _sanitise_error,
    cmd_agent_run,
    cmd_agents_describe,
    cmd_agents_list,
    cmd_benchmark_list,
    cmd_benchmark_report,
    cmd_benchmark_run,
    cmd_benchmark_validate,
    cmd_demo_run,
    cmd_evaluate,
    cmd_judge_score,
    cmd_replay,
    cmd_run,
    cmd_scenario_validate,
    cmd_trajectory_diagnose,
    cmd_trajectory_explain,
    cmd_trajectory_score,
    cmd_trajectory_validate,
    cmd_verify,
    cmd_verify_release,
    main,
)
from flight_agent_evaluator.contracts.model import (
    ModelConfiguration,
    ModelExchange,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
)
from flight_agent_evaluator.judges.evidence import build_evidence_package


def test_sanitise_error() -> None:
    exc = ValueError("Error in /path/to/secret/file.json occurred")
    sanitised = _sanitise_error(exc)
    assert "file.json" in sanitised
    assert "/path/to/secret" not in sanitised


def test_get_version() -> None:
    assert _get_version() == "0.2.0"


def test_cli_agents_list(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(json=False)
    assert cmd_agents_list(args) == 0
    captured = capsys.readouterr()
    assert "ScriptedOracleAgent" in captured.out

    args_json = argparse.Namespace(json=True)
    assert cmd_agents_list(args_json) == 0
    captured_json = capsys.readouterr()
    assert '"id": "scripted-oracle"' in captured_json.out


def test_cli_agents_describe(capsys: pytest.CaptureFixture[str]) -> None:
    for agent in (
        "oracle",
        "naive",
        "noop",
        "no-op",
        "model",
        "scripted-oracle",
        "naive-baseline",
        "no-op-baseline",
    ):
        args = argparse.Namespace(agent=agent, json=False)
        assert cmd_agents_describe(args) == 0
        captured = capsys.readouterr()
        assert "Class:" in captured.out

        args_json = argparse.Namespace(agent=agent, json=True)
        assert cmd_agents_describe(args_json) == 0
        captured_json = capsys.readouterr()
        assert '"id":' in captured_json.out

    args_invalid = argparse.Namespace(agent="unknown_agent_xyz", json=False)
    assert cmd_agents_describe(args_invalid) == 1


def test_cli_agent_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Oracle
    args = argparse.Namespace(
        scenario="resources/scenarios/jfk-lhr-delay.json",
        agent="oracle",
        model="gpt-4o-mini",
        model_mode="replay",
        allow_live_model=False,
        output=str(tmp_path),
        json=False,
    )
    assert cmd_agent_run(args) == 0
    captured = capsys.readouterr()
    assert "Agent Run Results" in captured.out

    # JSON mode
    args.json = True
    assert cmd_agent_run(args) == 0
    captured_json = capsys.readouterr()
    assert '"task_success": true' in captured_json.out

    # Naive
    args.agent = "naive"
    args.json = False
    assert cmd_agent_run(args) in (0, 1)

    # No-op
    args.agent = "noop"
    assert cmd_agent_run(args) in (0, 1)

    # Model in replay mode with manifest
    manifest_file = tmp_path / "model_manifest.json"
    req = ModelRequest(
        request_id="req-1",
        prompt_policy_id="p1",
        prompt_policy_version="1.0.0",
        prompt_digest="a" * 64,
        turn_index=0,
        messages=[{"role": "user", "content": "Check flight"}],
    )
    resp = ModelResponse(
        content='{"thought": "done", "action": {"tool_name": "flight.get_status", "parameters": {"flight_number": "AS142", "date": "2026-08-12"}}}',
    )
    mem = ModelExchangeManifest(
        manifest_id="mem-1",
        model_configuration=ModelConfiguration(),
        exchanges=[
            ModelExchange(
                turn_index=0,
                request=req,
                response=resp,
                request_fingerprint=req.canonical_fingerprint(),
                response_digest=resp.canonical_digest(),
            )
        ],
    )
    manifest_file.write_text(json.dumps(mem.model_dump(mode="json")), encoding="utf-8")

    args.agent = "model"
    args.model_mode = "replay"
    args.model_replay_manifest = str(manifest_file)
    assert cmd_agent_run(args) in (0, 1)

    # Model in live mode without flag
    args.model_mode = "live"
    args.allow_live_model = False
    with pytest.raises(Exception):
        cmd_agent_run(args)

    # Invalid scenario path
    args.scenario = "nonexistent.json"
    assert cmd_agent_run(args) == 1

    # Invalid agent
    args.scenario = "resources/scenarios/jfk-lhr-delay.json"
    args.agent = "unsupported_agent"
    assert cmd_agent_run(args) == 1


def test_cli_scenario_validate(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(scenario="resources/scenarios/jfk-lhr-delay.json", json=False)
    assert cmd_scenario_validate(args) == 0
    captured = capsys.readouterr()
    assert "is valid" in captured.out

    args_json = argparse.Namespace(scenario="resources/scenarios/jfk-lhr-delay.json", json=True)
    assert cmd_scenario_validate(args_json) == 0
    captured_json = capsys.readouterr()
    assert '"status": "valid"' in captured_json.out

    args_invalid = argparse.Namespace(scenario="nonexistent.json", json=False)
    assert cmd_scenario_validate(args_invalid) == 1

    args_invalid_json = argparse.Namespace(scenario="nonexistent.json", json=True)
    assert cmd_scenario_validate(args_invalid_json) == 1


def test_cli_trajectory_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Run scenario to produce recording
    args_run = argparse.Namespace(
        scenario="resources/scenarios/jfk-lhr-delay.json",
        output=str(tmp_path),
        json=False,
    )
    assert cmd_run(args_run) == 0
    captured = capsys.readouterr()
    run_id = captured.out.split("Run complete: ")[1].split("\n")[0].strip()

    rec_file = tmp_path / f"{run_id}.jsonl"
    exp_file = Path("resources/expectations/jfk-lhr-delay.json")

    # Validate expectation
    val_args = argparse.Namespace(expectation=str(exp_file), json=False)
    assert cmd_trajectory_validate(val_args) == 0
    val_args.json = True
    assert cmd_trajectory_validate(val_args) == 0

    val_invalid = argparse.Namespace(expectation="nonexistent.json", json=False)
    assert cmd_trajectory_validate(val_invalid) == 1

    # Score
    score_args = argparse.Namespace(
        recording=str(rec_file),
        expectation=str(exp_file),
        scenario=None,
        json=False,
    )
    assert cmd_trajectory_score(score_args) in (0, 1)
    captured = capsys.readouterr()
    assert "Trajectory Scorecard" in captured.out

    score_args.json = True
    assert cmd_trajectory_score(score_args) in (0, 1)

    # Explain
    exp_args = argparse.Namespace(
        recording=str(rec_file),
        expectation=str(exp_file),
        scenario=None,
        json=False,
    )
    assert cmd_trajectory_explain(exp_args) == 0
    exp_args.json = True
    assert cmd_trajectory_explain(exp_args) == 0

    # Diagnose
    diag_args = argparse.Namespace(
        recording=str(rec_file),
        expectation=str(exp_file),
        scenario=None,
        json=False,
    )
    assert cmd_trajectory_diagnose(diag_args) in (0, 1)
    diag_args.json = True
    assert cmd_trajectory_diagnose(diag_args) in (0, 1)

    # Replay playback & verify
    rep_args = argparse.Namespace(
        run_id=run_id,
        output=str(tmp_path),
        mode="playback",
        json=False,
    )
    assert cmd_replay(rep_args) == 0
    rep_args.json = True
    assert cmd_replay(rep_args) == 0

    rep_args.mode = "verify"
    rep_args.scenario = "resources/scenarios/jfk-lhr-delay.json"
    rep_args.json = False
    assert cmd_replay(rep_args) == 0
    rep_args.json = True
    assert cmd_replay(rep_args) == 0

    # Verify shortcut
    ver_args = argparse.Namespace(
        run_id=run_id,
        output=str(tmp_path),
        scenario="resources/scenarios/jfk-lhr-delay.json",
        json=False,
    )
    assert cmd_verify(ver_args) == 0

    # Evaluate
    eval_args = argparse.Namespace(
        run_id=run_id,
        scenario="resources/scenarios/jfk-lhr-delay.json",
        output=str(tmp_path),
        json=False,
    )
    assert cmd_evaluate(eval_args) == 0
    eval_args.json = True
    assert cmd_evaluate(eval_args) == 0


def test_cli_benchmark_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Benchmark list
    args_list = argparse.Namespace(json=False)
    assert cmd_benchmark_list(args_list) == 0
    args_list.json = True
    assert cmd_benchmark_list(args_list) == 0

    # Benchmark validate
    args_val = argparse.Namespace(
        manifest="builtin:benchmark-v1",
        manifest_pos=None,
        scenarios=None,
        json=False,
    )
    assert cmd_benchmark_validate(args_val) == 0
    args_val.json = True
    assert cmd_benchmark_validate(args_val) == 0

    # Benchmark run
    out_dir = tmp_path / "bm_out"
    args_run = argparse.Namespace(
        manifest="builtin:benchmark-v1",
        agents="scripted-oracle",
        repetitions=1,
        scenarios=None,
        output=str(out_dir),
        json=False,
    )
    assert cmd_benchmark_run(args_run) == 0
    captured = capsys.readouterr()
    assert "BENCHMARK EXECUTION SUMMARY" in captured.out

    # Benchmark report with summary file
    args_rep = argparse.Namespace(
        summary_file=str(out_dir / "summary.json"),
        results=None,
    )
    assert cmd_benchmark_report(args_rep) == 0
    captured = capsys.readouterr()
    assert "BENCHMARK EXECUTION REPORT" in captured.out

    # Benchmark report with run file
    args_rep2 = argparse.Namespace(
        summary_file=None,
        results=str(out_dir / "run.json"),
    )
    assert cmd_benchmark_report(args_rep2) == 0

    # Benchmark report with directory
    args_rep3 = argparse.Namespace(
        summary_file=str(out_dir),
        results=None,
    )
    assert cmd_benchmark_report(args_rep3) == 0


def test_cli_demo_and_verify_release(capsys: pytest.CaptureFixture[str]) -> None:
    demo_args = argparse.Namespace(json=False)
    assert cmd_demo_run(demo_args) == 0
    captured = capsys.readouterr()
    assert "PORTFOLIO DEMONSTRATION" in captured.out

    demo_args.json = True
    assert cmd_demo_run(demo_args) == 0

    rel_args = argparse.Namespace(json=False)
    assert cmd_verify_release(rel_args) == 0
    rel_args.json = True
    assert cmd_verify_release(rel_args) == 0


def test_cli_judge_score(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pkg = build_evidence_package(
        scenario_id="scen-1",
        run_id="run-1",
        public_task="Search flight",
        final_response="Found flight BA178",
    )
    pkg_file = tmp_path / "package.json"
    pkg_file.write_text(json.dumps(pkg.model_dump(mode="json")), encoding="utf-8")

    # Fake mode
    args = argparse.Namespace(package=str(pkg_file), mode="fake", json=False)
    assert cmd_judge_score(args) == 0
    captured = capsys.readouterr()
    assert "Qualitative Judge Evaluation" in captured.out

    args.json = True
    assert cmd_judge_score(args) == 0

    # Replay mode missing manifest
    args_replay = argparse.Namespace(
        package=str(pkg_file), mode="replay", manifest=None, json=False
    )
    assert cmd_judge_score(args_replay) == 1

    # Invalid package
    args_inv = argparse.Namespace(package="nonexistent.json", mode="fake", json=False)
    assert cmd_judge_score(args_inv) == 1


def test_cli_main_dispatch() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0

    assert main(["agents", "list", "--json"]) == 0
    assert main(["agents", "describe", "scripted-oracle", "--json"]) == 0
    assert main(["benchmark", "list", "--json"]) == 0
    assert main(["benchmark", "validate", "--manifest", "builtin:demo-v1", "--json"]) == 0
    assert main(["demo", "--json"]) == 0
    assert main(["benchmark", "verify-release", "--json"]) == 0

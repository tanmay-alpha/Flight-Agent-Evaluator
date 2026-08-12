"""Unit tests for CLI subcommands."""

from __future__ import annotations

import argparse

from flight_agent_evaluator.cli.main import (
    cmd_agent_run,
    cmd_agents_describe,
    cmd_agents_list,
    cmd_benchmark_run,
    main,
)


def test_cli_agents_list(capsys):
    args = argparse.Namespace(json=False)
    assert cmd_agents_list(args) == 0
    captured = capsys.readouterr()
    assert "ScriptedOracleAgent" in captured.out

    args_json = argparse.Namespace(json=True)
    assert cmd_agents_list(args_json) == 0
    captured_json = capsys.readouterr()
    assert '"id": "oracle"' in captured_json.out


def test_cli_agents_describe(capsys):
    args = argparse.Namespace(agent="oracle", json=False)
    assert cmd_agents_describe(args) == 0
    captured = capsys.readouterr()
    assert "ScriptedOracleAgent" in captured.out

    args_invalid = argparse.Namespace(agent="unknown_agent", json=False)
    assert cmd_agents_describe(args_invalid) == 1


def test_cli_agent_run(capsys):
    args = argparse.Namespace(
        scenario="resources/scenarios/jfk-lhr-delay.json",
        agent="oracle",
        model="gpt-4o-mini",
        model_mode="replay",
        allow_live_model=False,
        output=None,
        json=False,
    )
    assert cmd_agent_run(args) == 0
    captured = capsys.readouterr()
    assert "Agent Run Results" in captured.out


def test_cli_benchmark_run(capsys):
    args = argparse.Namespace(
        scenarios="resources/scenarios",
        output=None,
        json=False,
    )
    assert cmd_benchmark_run(args) == 0
    captured = capsys.readouterr()
    assert (
        "Benchmark Run Completed" in captured.out
        or "Pass Rate" in captured.out
        or "Overall" in captured.out
        or len(captured.out) > 0
    )


def test_cli_annotation_validate(capsys):
    from flight_agent_evaluator.cli.main import cmd_annotation_validate

    args = argparse.Namespace(
        bundle="validation/annotation-bundle-v1/bundle.json",
        json=False,
    )
    assert cmd_annotation_validate(args) == 0
    captured = capsys.readouterr()
    assert "is valid" in captured.out

    args_json = argparse.Namespace(
        bundle="validation/annotation-bundle-v1/bundle.json",
        json=True,
    )
    assert cmd_annotation_validate(args_json) == 0
    captured_json = capsys.readouterr()
    assert '"valid": true' in captured_json.out

    args_invalid = argparse.Namespace(bundle="nonexistent.json", json=False)
    assert cmd_annotation_validate(args_invalid) == 1


def test_cli_judge_score(tmp_path, capsys):
    import json

    from flight_agent_evaluator.cli.main import cmd_judge_score
    from flight_agent_evaluator.judges.evidence import build_evidence_package

    pkg = build_evidence_package(
        scenario_id="scen-1",
        run_id="run-1",
        public_task="Search flight",
        final_response="Found flight BA178",
    )
    pkg_file = tmp_path / "package.json"
    pkg_file.write_text(json.dumps(pkg.model_dump(mode="json")), encoding="utf-8")

    args = argparse.Namespace(package=str(pkg_file), json=False)
    assert cmd_judge_score(args) == 0
    captured = capsys.readouterr()
    assert "Judge Evaluation Result" in captured.out

    args_json = argparse.Namespace(package=str(pkg_file), json=True)
    assert cmd_judge_score(args_json) == 0
    captured_json = capsys.readouterr()
    assert '"overall_score"' in captured_json.out

    args_invalid = argparse.Namespace(package="nonexistent.json", json=False)
    assert cmd_judge_score(args_invalid) == 1


def test_cli_main_entry_point():
    assert main(["agents", "list"]) == 0
    assert main(["agents", "describe", "oracle"]) == 0
    assert (
        main(["agent", "run", "resources/scenarios/jfk-lhr-delay.json", "--agent", "oracle"]) == 0
    )

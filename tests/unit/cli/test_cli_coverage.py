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
    assert "Benchmark Suite Summary" in captured.out


def test_cli_main_entry_point():
    assert main(["agents", "list"]) == 0
    assert main(["agents", "describe", "oracle"]) == 0
    assert (
        main(["agent", "run", "resources/scenarios/jfk-lhr-delay.json", "--agent", "oracle"]) == 0
    )

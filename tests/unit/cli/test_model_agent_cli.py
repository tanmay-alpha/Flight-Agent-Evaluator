"""CLI regression tests for the model agent, live-model safety, agent registry, and judge mode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flight_agent_evaluator.cli.main import main
from flight_agent_evaluator.contracts.model import ModelConfiguration, ModelExchangeManifest

SCENARIO = "resources/scenarios/jfk-lhr-delay.json"
SECRET = "sk-proj-cli-test-SECRET-000000000000"


def test_live_model_without_allow_flag_is_a_clean_usage_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: this used to crash with a traceback."""
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    code = main(["agent", "run", SCENARIO, "--agent", "model", "--model-mode", "live"])
    captured = capsys.readouterr()
    assert code == 2
    assert "--allow-live-model" in captured.err
    assert "Traceback" not in captured.err
    assert SECRET not in captured.err + captured.out


def test_live_model_requires_named_api_key_env(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MY_GATEWAY_KEY", raising=False)
    code = main(
        [
            "agent",
            "run",
            SCENARIO,
            "--agent",
            "model",
            "--model-mode",
            "live",
            "--allow-live-model",
            "--api-key-env",
            "MY_GATEWAY_KEY",
            "--base-url",
            "http://127.0.0.1:11434/v1",
        ]
    )
    assert code == 2
    assert "MY_GATEWAY_KEY" in capsys.readouterr().err


def test_record_mode_requires_output(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    code = main(
        [
            "agent",
            "run",
            SCENARIO,
            "--agent",
            "model",
            "--model-mode",
            "record",
            "--allow-live-model",
        ]
    )
    assert code == 2
    assert "--output" in capsys.readouterr().err


def test_model_replay_requires_a_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["agent", "run", SCENARIO, "--agent", "model"])
    assert code == 2
    assert "--model-replay-manifest PATH" in capsys.readouterr().err


def test_model_replay_with_wrong_manifest_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_file = tmp_path / "m.model-exchanges.json"
    manifest_file.write_text(
        ModelExchangeManifest(
            manifest_id="other", model_configuration=ModelConfiguration()
        ).model_dump_json(),
        encoding="utf-8",
    )
    code = main(
        [
            "agent",
            "run",
            SCENARIO,
            "--agent",
            "model",
            "--model-replay-manifest",
            str(manifest_file),
        ]
    )
    assert code == 1
    assert "No recorded model exchange" in capsys.readouterr().err


def test_benchmark_run_model_replay_without_dir_is_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["benchmark", "run", "--agents", "model"])
    assert code == 2
    assert "--model-replay-dir" in capsys.readouterr().err


def test_benchmark_run_model_record_requires_allow_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    code = main(
        [
            "benchmark",
            "run",
            "--agents",
            "model",
            "--model-mode",
            "record",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 2
    assert "--allow-live-model" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_benchmark_run_refuses_network_model_for_release_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "benchmark",
            "run",
            "--agents",
            "model",
            "--model-mode",
            "record",
            "--allow-live-model",
            "--output",
            "results/benchmark-v1",
        ]
    )
    assert code == 2
    assert "source-release" in capsys.readouterr().err


def test_agents_list_and_describe_come_from_registry(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["agents", "list", "--json"]) == 0
    ids = [a["id"] for a in json.loads(capsys.readouterr().out)]
    assert ids == [
        "scripted-oracle",
        "naive-baseline",
        "no-op-baseline",
        "unsafe-baseline",
        "model",
    ]

    assert main(["agents", "describe", "unsafe", "--json"]) == 0
    described = json.loads(capsys.readouterr().out)
    assert described["id"] == "unsafe-baseline"
    assert described["mode"] == "negative_control"

    assert main(["agents", "describe", "random"]) == 1


def test_agents_describe_help_lists_no_phantom_agents(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["agents", "describe", "--help"])
    assert "random" not in capsys.readouterr().out


def test_unsafe_baseline_runs_from_cli(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "agent",
            "run",
            "resources/scenarios/transactional/approval-denied.json",
            "--agent",
            "unsafe-baseline",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert result["agent_id"] == "unsafe_baseline"
    assert code in (0, 1)


def test_judge_score_requires_explicit_mode(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["judge", "score", "package.json"])
    assert "--mode" in capsys.readouterr().err

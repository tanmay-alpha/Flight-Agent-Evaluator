"""Tests for ``python -m flight_agent_evaluator.traces``."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from flight_agent_evaluator.traces.cli import EXIT_FAILED, EXIT_INPUT_ERROR, EXIT_PASSED, main

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "traces"


def test_cli_text_report_for_correct_example(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(EXAMPLES / "jfk-lhr-delay.correct.json")]) == EXIT_PASSED
    out = capsys.readouterr().out
    assert "Scenario:        jfk-lhr-delay" in out
    assert "Task success:    True" in out
    assert "framework=none (hand-written example)" in out
    assert "Trace consistent with environment: True" in out


def test_cli_json_report_lists_divergences(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(EXAMPLES / "approval-denied.unsafe.json"), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["scenario_id"] == "approval-denied"
    assert report["trace_consistent"] is False
    assert report["divergences"][0]["tool_name"] == "booking.confirm_rebooking"
    passed = report["metrics"]["task_success"] and report["metrics"]["safety_pass"]
    assert code == (EXIT_PASSED if passed else EXIT_FAILED)


def test_cli_text_report_includes_divergences(capsys: pytest.CaptureFixture[str]) -> None:
    main([str(EXAMPLES / "approval-denied.unsafe.json")])
    out = capsys.readouterr().out
    assert "  - trace_divergence[status_mismatch] call 3 (booking.confirm_rebooking)" in out


def test_cli_failed_run_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = json.loads((EXAMPLES / "jfk-lhr-delay.correct.json").read_text("utf-8"))
    doc["calls"] = []
    doc["agent"]["model"] = "m"
    path = tmp_path / "empty.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert main([str(path)]) == EXIT_FAILED
    out = capsys.readouterr().out
    assert "Task success:    False" in out
    assert "model=m" in out


def test_cli_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version": "9"}', encoding="utf-8")
    assert main([str(path)]) == EXIT_INPUT_ERROR
    assert "Unsupported trace schema_version" in capsys.readouterr().err


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["traces", str(tmp_path / "missing.json")])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("flight_agent_evaluator.traces", run_name="__main__")
    assert exc.value.code == EXIT_INPUT_ERROR

"""Tests for ``python -m flight_agent_evaluator.traces``."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

import flight_agent_evaluator
from flight_agent_evaluator.traces import cli as trace_cli, evaluate_trace, load_trace
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
    assert capsys.readouterr().err == (
        "error: trace or referenced scenario/expectation could not be loaded\n"
    )


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "argv", ["traces", str(tmp_path / "missing.json")])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("flight_agent_evaluator.traces", run_name="__main__")
    assert exc.value.code == EXIT_INPUT_ERROR


@pytest.mark.parametrize(
    "document",
    [
        '{"schema_version":"SECRET_CONTENT /absolute/private/path"}',
        '{"schema_version":"1.0","schema_version":"SECRET_CONTENT"}',
        '{"schema_version":"1.0","scenario":{"path":"C:\\\\SECRET_CONTENT.json"},'
        '"agent":{"name":"a"},"calls":[]}',
    ],
)
def test_cli_input_errors_do_not_echo_content_or_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], document: str
) -> None:
    path = tmp_path / "SECRET_FILENAME.json"
    path.write_text(document, encoding="utf-8")
    assert main([str(path), "--json"]) == EXIT_INPUT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "SECRET" not in captured.err
    assert str(tmp_path) not in captured.err
    assert "/absolute" not in captured.err


def test_cli_sanitizes_underlying_resolution_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise ValueError(f"SECRET_CONTENT {tmp_path.resolve()}")

    monkeypatch.setattr(trace_cli, "evaluate_trace", fail)
    assert main([str(EXAMPLES / "jfk-lhr-delay.correct.json")]) == EXIT_INPUT_ERROR
    error = capsys.readouterr().err
    assert "SECRET_CONTENT" not in error
    assert str(tmp_path.resolve()) not in error


def test_cli_missing_file_error_hides_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(tmp_path / "SECRET_MISSING.json")]) == EXIT_INPUT_ERROR
    error = capsys.readouterr().err
    assert "SECRET" not in error and str(tmp_path) not in error


def test_cli_allow_root_loads_relative_references(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    resources = Path(flight_agent_evaluator.__file__).resolve().parent / "resources"
    doc = json.loads((EXAMPLES / "jfk-lhr-delay.correct.json").read_text("utf-8"))
    doc["scenario"] = {
        "path": "scenarios/jfk-lhr-delay.json",
        "expectation_path": "expectations/jfk-lhr-delay.json",
    }
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert main([str(path)]) == EXIT_INPUT_ERROR
    capsys.readouterr()
    assert main([str(path), "--allow-root", str(resources), "--json"]) == EXIT_PASSED
    report = json.loads(capsys.readouterr().out)
    assert report["metrics"]["task_success"] is True


def test_cli_transcript_example_preserves_intermediate_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([str(EXAMPLES / "jfk-lhr-delay.openai-chat.json"), "--json"]) == EXIT_PASSED
    report = json.loads(capsys.readouterr().out)
    assert report["source"]["format"] == "openai_chat"
    assert report["source"]["intermediate_assistant_content"][0]["tool_call_ids"] == [
        "status-call",
        "search-call",
    ]
    assert report["trace_consistent"] is True


def test_text_report_includes_failure_evidence_and_remediation() -> None:
    report = evaluate_trace(load_trace(EXAMPLES / "jfk-lhr-delay.correct.json"))
    metrics = type(report.metrics).model_validate(
        {
            **report.metrics.model_dump(),
            "failure_codes": ["required_action_missing"],
            "failure_details": [
                {
                    "code": "required_action_missing",
                    "severity": "error",
                    "message": "A required action is missing.",
                    "evidence_sequences": [2, 4],
                    "remediation": "Perform the required status lookup.",
                }
            ],
        }
    )
    rendered = trace_cli.render_text(report.model_copy(update={"metrics": metrics}))
    assert "[error] required_action_missing: A required action is missing." in rendered
    assert "Evidence sequences: [2, 4]" in rendered
    assert "Remediation: Perform the required status lookup." in rendered

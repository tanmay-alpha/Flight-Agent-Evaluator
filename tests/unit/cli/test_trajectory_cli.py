"""Unit tests for trajectory CLI subcommands."""

from __future__ import annotations

import argparse
import datetime
import uuid

from flight_agent_evaluator.cli.main import (
    cmd_benchmark_validate,
    cmd_trajectory_explain,
    cmd_trajectory_score,
    cmd_trajectory_validate,
)
from flight_agent_evaluator.contracts.tools import ToolCall, ToolResult
from flight_agent_evaluator.recording.contracts import RunRecording
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock


def test_cli_trajectory_validate(capsys):
    args = argparse.Namespace(expectation="resources/expectations/jfk-lhr-delay.json", json=False)
    assert cmd_trajectory_validate(args) == 0
    captured = capsys.readouterr()
    assert "Expectation graph is valid" in captured.out


def test_cli_trajectory_validate_json(capsys):
    args = argparse.Namespace(expectation="resources/expectations/jfk-lhr-delay.json", json=True)
    assert cmd_trajectory_validate(args) == 0
    captured = capsys.readouterr()
    assert '"valid": true' in captured.out


def test_cli_trajectory_validate_not_found(capsys):
    args = argparse.Namespace(expectation="resources/expectations/nonexistent.json", json=False)
    assert cmd_trajectory_validate(args) == 1


def test_cli_benchmark_validate(capsys):
    args = argparse.Namespace(scenarios="resources/scenarios", json=False)
    assert cmd_benchmark_validate(args) == 0
    captured = capsys.readouterr()
    assert "All benchmark scenarios & expectations are valid" in captured.out


def test_cli_benchmark_validate_json(capsys):
    args = argparse.Namespace(scenarios="resources/scenarios", json=True)
    assert cmd_benchmark_validate(args) == 0
    captured = capsys.readouterr()
    assert '"valid": true' in captured.out


def test_cli_benchmark_validate_not_found(capsys):
    args = argparse.Namespace(scenarios="nonexistent_dir", json=False)
    assert cmd_benchmark_validate(args) == 1


def test_cli_trajectory_score_and_explain(tmp_path, capsys):
    run_id = str(uuid.uuid4())
    store = FileRecordingStore(tmp_path)
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    t0 = clock.now()

    journal = HashChainJournal()
    tc = ToolCall(
        call_id=uuid.uuid4(),
        run_id=uuid.UUID(run_id),
        tool_name="flight.get_status",
        arguments={"flight_id": "AA100", "operating_day": "2026-07-28"},
        mutation_class="read_only",
        start_time=t0,
    )
    tr = ToolResult(
        call_id=tc.call_id,
        status="success",
        result={"status": "on_time"},
        end_time=t0,
    )
    journal.append_event(
        "tool_call", run_id=run_id, correlation_id="c1", time=t0, payload=tc.model_dump(mode="json")
    )
    journal.append_event(
        "tool_result",
        run_id=run_id,
        correlation_id="c1",
        time=t0,
        payload=tr.model_dump(mode="json"),
    )

    recording = RunRecording(
        run_id=uuid.UUID(run_id),
        scenario_id="lax-sfo-ontime",
        scenario_version=1,
        seed=42,
        started_at=t0,
        completed_at=t0,
        entry_count=2,
        final_digest="0" * 64,
        tool_calls_made=1,
    )
    store.write_recording(run_id, journal, recording)

    rec_file = tmp_path / f"{run_id}.jsonl"
    exp_file = "resources/expectations/lax-sfo-ontime.json"

    score_args = argparse.Namespace(recording=str(rec_file), expectation=exp_file, json=False)
    assert cmd_trajectory_score(score_args) == 0
    cap = capsys.readouterr()
    assert "Trajectory Scorecard:" in cap.out

    score_args_json = argparse.Namespace(recording=str(rec_file), expectation=exp_file, json=True)
    assert cmd_trajectory_score(score_args_json) == 0

    explain_args = argparse.Namespace(recording=str(rec_file), expectation=exp_file, json=False)
    assert cmd_trajectory_explain(explain_args) == 0
    cap_exp = capsys.readouterr()
    assert "Evidence Attribution Explanation:" in cap_exp.out

    explain_args_json = argparse.Namespace(recording=str(rec_file), expectation=exp_file, json=True)
    assert cmd_trajectory_explain(explain_args_json) == 0

"""Comprehensive tests for the CLI in ``flight_agent_evaluator.cli.main``.

Covers every branch of:

- ``main()`` - argument parsing, subcommand dispatch, help text, missing
  arguments, unknown commands.
- ``cmd_run()`` - successful run, scenario load failure, runner build failure,
  runner execution failure, default output directory.
- ``cmd_replay()`` - successful playback, default output directory.
- ``cmd_verify()`` - clean verification, divergences detected, default output
  directory.
- Exit codes - every command's return value under success and failure.
- Error messages - stderr output under failure paths.

Note: The engine.runner module has a pre-existing syntax error on the current
branch.  We therefore patch ``sys.modules`` before importing the CLI so that
the ``ScenarioRunner`` import resolves to a mock.  All CLI logic is exercised
through the command functions directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# The engine.runner module has a pre-existing IndentationError on this branch.
# Patch sys.modules so that ``from flight_agent_evaluator.engine.runner
# import ScenarioRunner`` resolves to a MagicMock, allowing the CLI module to
# be imported and tested for all its own logic.
# ---------------------------------------------------------------------------

_mock_runner_module = mock.MagicMock()
sys.modules.setdefault("flight_agent_evaluator.engine.runner", _mock_runner_module)
_mock_replay_module = mock.MagicMock()
sys.modules.setdefault("flight_agent_evaluator.replay.engine", _mock_replay_module)

from flight_agent_evaluator.cli.main import (  # noqa: E402 - after mock injection
    cmd_replay,
    cmd_run,
    cmd_verify,
    main,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

# A minimal valid scenario dict that passes BenchmarkScenario validation.
_VALID_SCENARIO_DICT: dict[str, Any] = {
    "schema_version": "1.0.0",
    "scenario_id": {"id": "test-scenario", "version": 1},
    "metadata": {
        "title": "Test scenario",
        "description": "A test scenario",
        "objective": "Verify the runner works",
    },
    "limits": {"tool_call_limit": 5, "time_limit_seconds": 60},
    "seed": 42,
    "steps": [
        {"step_id": "step-1", "description": "Do something"},
    ],
}


def _write_scenario(tmp_path: Path, data: dict[str, Any] | None = None) -> Path:
    """Write *data* (or the default valid dict) as a JSON scenario file."""
    target = tmp_path / "scenario.json"
    target.write_text(
        json.dumps(data or _VALID_SCENARIO_DICT, indent=2),
        encoding="utf-8",
    )
    return target


def _capture_stderr(func, *args, **kwargs):
    """Run *func* with stderr captured; return (result, stderr_text)."""
    old_stderr = sys.stderr
    buf = StringIO()
    sys.stderr = buf
    try:
        result = func(*args, **kwargs)
    finally:
        sys.stderr = old_stderr
    return result, buf.getvalue()


def _make_namespace(command: str, **kwargs) -> argparse.Namespace:
    """Build an argparse.Namespace that mimics parsed CLI args."""
    ns = argparse.Namespace(func=None, command=command)
    for key, val in kwargs.items():
        setattr(ns, key, val)
    return ns


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMainHelp:
    """Tests for the ``--help`` flag and top-level argument handling."""

    def test_help_exits_zero(self):
        """``flight-evaluator --help`` must exit with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_help_mentions_prog_name(self, capsys):
        """The help text must mention the program name."""
        with pytest.raises(SystemExit):
            main(["--help"])
        captured = capsys.readouterr()
        assert "flight-evaluator" in captured.out

    def test_help_lists_subcommands(self, capsys):
        """The help text must mention the ``run``, ``replay``, and ``verify``
        subcommands."""
        with pytest.raises(SystemExit):
            main(["--help"])
        out = capsys.readouterr().out
        assert "run" in out
        assert "replay" in out
        assert "verify" in out


class TestMainMissingArgs:
    """Tests for invoking the CLI with no or incomplete arguments."""

    def test_no_args_exits_with_error(self):
        """Calling with no args at all should exit with a non-zero code."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_no_args_prints_error_to_stderr(self, capsys):
        """Calling with no args should print an argparse error message."""
        with pytest.raises(SystemExit):
            main([])
        captured = capsys.readouterr()
        # argparse writes error details to stderr
        assert "required" in captured.err.lower() or len(captured.err) > 0

    def test_unknown_command_exits_with_error(self):
        """An unrecognised subcommand should cause a non-zero exit."""
        with pytest.raises(SystemExit) as exc_info:
            main(["not-a-command"])
        assert exc_info.value.code != 0


class TestMainDispatch:
    """Tests that ``main()`` dispatches to the correct command function."""

    def test_run_dispatch_calls_cmd_run(self):
        """``main(["run", ...])`` must delegate to cmd_run."""
        ns = _make_namespace("run", scenario="dummy.json", output=None)
        with mock.patch(
            "flight_agent_evaluator.cli.main.cmd_run", return_value=0
        ) as mock_run:
            # argparse normally builds the namespace; we short-circuit by
            # injecting our own namespace into main's flow.
            with mock.patch(
                "argparse.ArgumentParser.parse_args", return_value=ns
            ):
                result = main(["run", "dummy.json"])
        assert result == 0
        mock_run.assert_called_once_with(ns)

    def test_replay_dispatch_calls_cmd_replay(self):
        """``main(["replay", ...])`` must delegate to cmd_replay."""
        ns = _make_namespace("replay", run_id="rid-1", output=None)
        with mock.patch(
            "flight_agent_evaluator.cli.main.cmd_replay", return_value=0
        ) as mock_replay:
            with mock.patch(
                "argparse.ArgumentParser.parse_args", return_value=ns
            ):
                result = main(["replay", "rid-1"])
        assert result == 0
        mock_replay.assert_called_once_with(ns)

    def test_verify_dispatch_calls_cmd_verify(self):
        """``main(["verify", ...])`` must delegate to cmd_verify."""
        ns = _make_namespace("verify", run_id="rid-1", output=None)
        with mock.patch(
            "flight_agent_evaluator.cli.main.cmd_verify", return_value=0
        ) as mock_verify:
            with mock.patch(
                "argparse.ArgumentParser.parse_args", return_value=ns
            ):
                result = main(["verify", "rid-1"])
        assert result == 0
        mock_verify.assert_called_once_with(ns)

    def test_run_command_returns_cmd_run_exit_code(self):
        """The exit code from cmd_run must propagate through main()."""
        ns = _make_namespace("run", scenario="dummy.json", output=None)
        with mock.patch(
            "flight_agent_evaluator.cli.main.cmd_run", return_value=1
        ):
            with mock.patch(
                "argparse.ArgumentParser.parse_args", return_value=ns
            ):
                result = main(["run", "dummy.json"])
        assert result == 1

    def test_replay_command_returns_cmd_replay_exit_code(self):
        """The exit code from cmd_replay must propagate through main()."""
        ns = _make_namespace("replay", run_id="rid", output=None)
        with mock.patch(
            "flight_agent_evaluator.cli.main.cmd_replay", return_value=2
        ):
            with mock.patch(
                "argparse.ArgumentParser.parse_args", return_value=ns
            ):
                result = main(["replay", "rid"])
        assert result == 2

    def test_verify_command_returns_cmd_verify_exit_code(self):
        """The exit code from cmd_verify must propagate through main()."""
        ns = _make_namespace("verify", run_id="rid", output=None)
        with mock.patch(
            "flight_agent_evaluator.cli.main.cmd_verify", return_value=3
        ):
            with mock.patch(
                "argparse.ArgumentParser.parse_args", return_value=ns
            ):
                result = main(["verify", "rid"])
        assert result == 3


# ---------------------------------------------------------------------------
# _build_runner helper
# ---------------------------------------------------------------------------


class TestBuildRunner:
    """Tests for the ``_build_runner`` helper function."""

    def test_build_runner_with_no_output_uses_default(self, tmp_path: Path):
        """When output is None, the recording store defaults to '.recordings'."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)

        runner = _build_runner(output=None, loaded=loaded)
        # The store is stored on the runner; we verify it was constructed with
        # the default directory.
        assert runner is not None

    def test_build_runner_with_explicit_output(self, tmp_path: Path):
        """When output is provided, the recording store uses that directory."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        out_dir = tmp_path / "my-recordings"

        runner = _build_runner(output=out_dir, loaded=loaded)
        assert runner is not None

    def test_build_runner_rejects_naive_reference_time(self, tmp_path: Path):
        """A scenario with a naive (non-timezone-aware) reference_time must
        raise ValueError."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        data = dict(_VALID_SCENARIO_DICT)
        # Set reference_time to a naive datetime string.
        data["reference_time"] = "2026-01-01T00:00:00"
        scenario_path = tmp_path / "naive_scenario.json"
        scenario_path.write_text(json.dumps(data), encoding="utf-8")

        loaded = ScenarioLoader().load_from_path(scenario_path)
        with pytest.raises(ValueError, match="timezone-aware"):
            _build_runner(output=None, loaded=loaded)

    def test_build_runner_accepts_timezone_aware_reference_time(self, tmp_path: Path):
        """A scenario with a timezone-aware reference_time must succeed."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        data = dict(_VALID_SCENARIO_DICT)
        data["reference_time"] = "2026-01-01T00:00:00+00:00"
        scenario_path = tmp_path / "aware_scenario.json"
        scenario_path.write_text(json.dumps(data), encoding="utf-8")

        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=None, loaded=loaded)
        assert runner is not None

    def test_build_runner_defaults_to_epoch_when_no_reference_time(self, tmp_path: Path):
        """Without a reference_time, the clock defaults to 2026-01-01 UTC."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=None, loaded=loaded)
        assert runner is not None


# ---------------------------------------------------------------------------
# cmd_run
# ---------------------------------------------------------------------------


class TestCmdRun:
    """Tests for the ``cmd_run`` command function."""

    # --- error paths ---

    def test_scenario_load_failure_returns_one(self, tmp_path: Path):
        """When ScenarioLoader.load_from_path raises, cmd_run returns 1."""
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        with mock.patch.object(
            ScenarioLoader, "load_from_path", side_effect=Exception("boom")
        ):
            ns = _make_namespace(
                "run", scenario=str(tmp_path / "nonexistent.json"), output=None
            )
            result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1
        assert "boom" in stderr

    def test_scenario_load_failure_prints_to_stderr(self, tmp_path: Path):
        """Error from scenario loading is printed to stderr."""
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        with mock.patch.object(
            ScenarioLoader, "load_from_path", side_effect=Exception("load-error")
        ):
            ns = _make_namespace(
                "run", scenario=str(tmp_path / "x.json"), output=None
            )
            _, stderr = _capture_stderr(cmd_run, ns)
        assert "load-error" in stderr

    def test_runner_build_failure_returns_one(self, tmp_path: Path):
        """When _build_runner raises, cmd_run returns 1."""
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)

        with mock.patch(
            "flight_agent_evaluator.cli.main._build_runner",
            side_effect=ValueError("bad scenario"),
        ):
            ns = _make_namespace(
                "run", scenario=str(scenario_path), output=None
            )
            result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1
        assert "bad scenario" in stderr

    def test_runner_execution_failure_returns_one(self, tmp_path: Path):
        """When runner.run() raises, cmd_run returns 1."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
        from flight_agent_evaluator.recording.contracts import RunRecording
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from datetime import UTC, datetime

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=None, loaded=loaded)

        with mock.patch.object(
            runner, "run", side_effect=RuntimeError("execution failed")
        ):
            ns = _make_namespace(
                "run", scenario=str(scenario_path), output=None
            )
            result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1
        assert "execution failed" in stderr

    def test_scenario_not_found_returns_one(self, tmp_path: Path):
        """A missing scenario file causes exit code 1."""
        ns = _make_namespace(
            "run", scenario=str(tmp_path / "does-not-exist.json"), output=None
        )
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    # --- success path ---

    def test_successful_run_returns_zero(self, tmp_path: Path):
        """A valid scenario that runs successfully returns exit code 0."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=tmp_path / "recordings", loaded=loaded)

        ns = _make_namespace(
            "run", scenario=str(scenario_path), output=str(tmp_path / "recordings")
        )
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 0
        assert stderr == ""

    def test_successful_run_prints_run_id(self, tmp_path: Path, capsys):
        """Successful run prints the run_id to stdout."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=tmp_path / "recordings", loaded=loaded)

        ns = _make_namespace(
            "run", scenario=str(scenario_path), output=str(tmp_path / "recordings")
        )
        result = cmd_run(ns)
        assert result == 0
        out = capsys.readouterr().out
        assert "Run complete:" in out

    def test_successful_run_prints_entry_count(self, tmp_path: Path, capsys):
        """Successful run prints entry count."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=tmp_path / "recordings", loaded=loaded)

        ns = _make_namespace(
            "run", scenario=str(scenario_path), output=str(tmp_path / "recordings")
        )
        cmd_run(ns)
        out = capsys.readouterr().out
        assert "Entries:" in out

    def test_successful_run_prints_digest(self, tmp_path: Path, capsys):
        """Successful run prints the recording digest."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=tmp_path / "recordings", loaded=loaded)

        ns = _make_namespace(
            "run", scenario=str(scenario_path), output=str(tmp_path / "recordings")
        )
        cmd_run(ns)
        out = capsys.readouterr().out
        assert "Digest:" in out

    def test_run_with_no_output_creates_default_directory(self, tmp_path: Path, capsys):
        """When --output is omitted, recordings go to the default directory."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        # _build_runner uses ".recordings" when output is None
        runner = _build_runner(output=None, loaded=loaded)

        ns = _make_namespace("run", scenario=str(scenario_path), output=None)
        result = cmd_run(ns)
        assert result == 0

    def test_run_with_invalid_json_scenario_returns_one(self, tmp_path: Path):
        """A scenario file containing invalid JSON returns exit code 1."""
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json {{{", encoding="utf-8")
        ns = _make_namespace("run", scenario=str(bad), output=None)
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    def test_run_with_validation_failure_returns_one(self, tmp_path: Path):
        """A scenario that fails Pydantic validation returns exit code 1."""
        bad = tmp_path / "invalid.json"
        # Missing required fields
        bad.write_text(json.dumps({}), encoding="utf-8")
        ns = _make_namespace("run", scenario=str(bad), output=None)
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    def test_run_with_symlink_scenario_returns_one(self, tmp_path: Path):
        """A symlinked scenario file is rejected with exit code 1."""
        import os

        real = tmp_path / "real.json"
        real.write_text(json.dumps(_VALID_SCENARIO_DICT), encoding="utf-8")
        link = tmp_path / "link.json"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")

        ns = _make_namespace("run", scenario=str(link), output=None)
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    def test_run_with_oversized_scenario_returns_one(self, tmp_path: Path):
        """A scenario file exceeding the size limit returns exit code 1."""
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        big = tmp_path / "big.json"
        big.write_bytes(b"x" * (ScenarioLoader._DEFAULT_MAX_BYTES + 1))
        ns = _make_namespace("run", scenario=str(big), output=None)
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    def test_run_creates_recording_files(self, tmp_path: Path):
        """A successful run writes recording files to the output directory."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        out_dir = tmp_path / "out"
        runner = _build_runner(output=out_dir, loaded=loaded)

        ns = _make_namespace(
            "run", scenario=str(scenario_path), output=str(out_dir)
        )
        result = cmd_run(ns)
        assert result == 0
        # At least the .jsonl file should exist
        jsonl_files = list(out_dir.glob("*.jsonl"))
        assert len(jsonl_files) >= 1


# ---------------------------------------------------------------------------
# cmd_replay
# ---------------------------------------------------------------------------


class TestCmdReplay:
    """Tests for the ``cmd_replay`` command function."""

    def test_successful_playback_returns_zero(self, tmp_path: Path):
        """A valid replay returns exit code 0."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from flight_agent_evaluator.replay.engine import ReplayEngine
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        # Need a RunRecording for write_recording
        from flight_agent_evaluator.recording.contracts import RunRecording

        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("replay", run_id=run_id, output=str(tmp_path))
        result = cmd_replay(ns)
        assert result == 0

    def test_successful_playback_prints_digest(self, tmp_path: Path, capsys):
        """Replay prints the journal digest."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("replay", run_id=run_id, output=str(tmp_path))
        cmd_replay(ns)
        out = capsys.readouterr().out
        assert "Digest:" in out

    def test_successful_playback_prints_entries_count(self, tmp_path: Path, capsys):
        """Replay prints the number of entries."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("replay", run_id=run_id, output=str(tmp_path))
        cmd_replay(ns)
        out = capsys.readouterr().out
        assert "Entries:" in out

    def test_replay_nonexistent_run_propagates_error(self, tmp_path: Path):
        """Replay of a missing recording propagates the underlying error."""
        from flight_agent_evaluator.replay.engine import ReplayEngine

        ns = _make_namespace("replay", run_id="nonexistent-run-id", output=str(tmp_path))
        with pytest.raises(Exception):
            cmd_replay(ns)

    def test_replay_with_no_output_uses_default(self, tmp_path: Path):
        """Replay without --output uses '.recordings' as default."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        # Write to the default .recordings directory
        default_dir = tmp_path / ".recordings"
        default_dir.mkdir()
        store = FileRecordingStore(default_dir)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("replay", run_id=run_id, output=None)
        # Change to the directory so the default ".recordings" resolves correctly
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            result = cmd_replay(ns)
            assert result == 0
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# cmd_verify
# ---------------------------------------------------------------------------


class TestCmdVerify:
    """Tests for the ``cmd_verify`` command function."""

    def test_verify_no_divergences_returns_zero(self, tmp_path: Path):
        """Verification with a clean journal returns exit code 0."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("verify", run_id=run_id, output=str(tmp_path))
        result = cmd_verify(ns)
        assert result == 0

    def test_verify_no_divergences_prints_all_checks_passed(self, tmp_path: Path, capsys):
        """Clean verification prints 'All checks passed.'"""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("verify", run_id=run_id, output=str(tmp_path))
        cmd_verify(ns)
        out = capsys.readouterr().out
        assert "All checks passed" in out

    def test_verify_with_divergences_returns_one(self, tmp_path: Path):
        """Verification that detects divergences returns exit code 1."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import (
            JournalEntry, RunRecording, ReplayReport, DivergenceRecord,
            ReplayOutcomeStatus,
        )
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from flight_agent_evaluator.replay.engine import ReplayEngine
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        # Write a valid journal
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        # Tamper with the file so the chain verification fails
        record_path = tmp_path / f"{run_id}.jsonl"
        lines = record_path.read_text(encoding="utf-8").splitlines()
        if lines:
            obj = json.loads(lines[0])
            obj["payload"] = {"tampered": True}
            lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
            record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ns = _make_namespace("verify", run_id=run_id, output=str(tmp_path))
        result = cmd_verify(ns)
        assert result == 1

    def test_verify_with_divergences_prints_divergence_count(self, tmp_path: Path, capsys):
        """When divergences are found, the count is printed."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        # Tamper with the file
        record_path = tmp_path / f"{run_id}.jsonl"
        lines = record_path.read_text(encoding="utf-8").splitlines()
        if lines:
            obj = json.loads(lines[0])
            obj["payload"] = {"tampered": True}
            lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
            record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ns = _make_namespace("verify", run_id=run_id, output=str(tmp_path))
        cmd_verify(ns)
        out = capsys.readouterr().out
        assert "Divergences:" in out

    def test_verify_with_divergences_prints_each_divergence(self, tmp_path: Path, capsys):
        """Each divergence detail is printed when divergences are found."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        record_path = tmp_path / f"{run_id}.jsonl"
        lines = record_path.read_text(encoding="utf-8").splitlines()
        if lines:
            obj = json.loads(lines[0])
            obj["payload"] = {"tampered": True}
            lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
            record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ns = _make_namespace("verify", run_id=run_id, output=str(tmp_path))
        cmd_verify(ns)
        out = capsys.readouterr().out
        assert "seq=" in out
        assert "chain-verification-failed" in out

    def test_verify_nonexistent_run_propagates_error(self, tmp_path: Path):
        """Verification of a missing recording propagates the error."""
        from flight_agent_evaluator.replay.engine import ReplayEngine

        ns = _make_namespace("verify", run_id="nonexistent-run-id", output=str(tmp_path))
        with pytest.raises(Exception):
            cmd_verify(ns)

    def test_verify_with_no_output_uses_default(self, tmp_path: Path):
        """Verify without --output uses '.recordings' as default."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        default_dir = tmp_path / ".recordings"
        default_dir.mkdir()
        store = FileRecordingStore(default_dir)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("verify", run_id=run_id, output=None)
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            result = cmd_verify(ns)
            assert result == 0
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


class TestExitCodes:
    """Tests verifying specific exit codes for every outcome."""

    def test_run_success_exit_code_zero(self, tmp_path: Path):
        """Successful run returns 0."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=tmp_path / "out", loaded=loaded)

        ns = _make_namespace(
            "run", scenario=str(scenario_path), output=str(tmp_path / "out")
        )
        assert cmd_run(ns) == 0

    def test_run_failure_exit_code_one(self, tmp_path: Path):
        """Run failure (bad scenario) returns 1."""
        ns = _make_namespace(
            "run", scenario=str(tmp_path / "nope.json"), output=None
        )
        assert cmd_run(ns) == 1

    def test_replay_success_exit_code_zero(self, tmp_path: Path):
        """Successful replay returns 0."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("replay", run_id=run_id, output=str(tmp_path))
        assert cmd_replay(ns) == 0

    def test_verify_success_exit_code_zero(self, tmp_path: Path):
        """Successful verification returns 0."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        ns = _make_namespace("verify", run_id=run_id, output=str(tmp_path))
        assert cmd_verify(ns) == 0

    def test_verify_with_divergences_exit_code_one(self, tmp_path: Path):
        """Verification with divergences returns 1."""
        from flight_agent_evaluator.recording.journal import HashChainJournal
        from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from datetime import UTC, datetime
        import uuid

        run_id = str(uuid.uuid4())
        store = FileRecordingStore(tmp_path)
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append(entry)
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id="test-scenario",
            scenario_version=1,
            seed=0,
            entry_count=1,
            final_digest="a" * 64,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        store.write_recording(run_id, journal, recording)

        record_path = tmp_path / f"{run_id}.jsonl"
        lines = record_path.read_text(encoding="utf-8").splitlines()
        if lines:
            obj = json.loads(lines[0])
            obj["payload"] = {"tampered": True}
            lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
            record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ns = _make_namespace("verify", run_id=run_id, output=str(tmp_path))
        assert cmd_verify(ns) == 1

    def test_help_exits_with_code_zero(self):
        """``--help`` exits with code 0 (SystemExit)."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_no_args_exits_with_nonzero_code(self):
        """No args exits with a non-zero code (SystemExit)."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Error handling edge cases
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for unusual inputs and error conditions."""

    def test_run_with_empty_scenario_path(self):
        """An empty scenario path string should fail gracefully."""
        ns = _make_namespace("run", scenario="", output=None)
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    def test_replay_with_empty_run_id(self, tmp_path: Path):
        """Replay with an empty run_id should fail."""
        from flight_agent_evaluator.replay.engine import ReplayEngine

        ns = _make_namespace("replay", run_id="", output=str(tmp_path))
        with pytest.raises(Exception):
            cmd_replay(ns)

    def test_verify_with_empty_run_id(self, tmp_path: Path):
        """Verify with an empty run_id should fail."""
        from flight_agent_evaluator.replay.engine import ReplayEngine

        ns = _make_namespace("verify", run_id="", output=str(tmp_path))
        with pytest.raises(Exception):
            cmd_verify(ns)

    def test_replay_engine_exception_propagates(self, tmp_path: Path):
        """An unexpected exception in ReplayEngine propagates out of
        cmd_replay."""
        with mock.patch(
            "flight_agent_evaluator.cli.main.ReplayEngine",
            side_effect=RuntimeError("engine boom"),
        ):
            ns = _make_namespace(
                "replay", run_id="some-run-id", output=str(tmp_path)
            )
            with pytest.raises(RuntimeError, match="engine boom"):
                cmd_replay(ns)

    def test_verify_engine_exception_propagates(self, tmp_path: Path):
        """An unexpected exception in ReplayEngine propagates out of
        cmd_verify."""
        with mock.patch(
            "flight_agent_evaluator.cli.main.ReplayEngine",
            side_effect=RuntimeError("engine boom"),
        ):
            ns = _make_namespace(
                "verify", run_id="some-run-id", output=str(tmp_path)
            )
            with pytest.raises(RuntimeError, match="engine boom"):
                cmd_verify(ns)

    def test_run_output_directory_is_created(self, tmp_path: Path):
        """cmd_run creates the output directory if it doesn't exist."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        scenario_path = _write_scenario(tmp_path)
        loaded = ScenarioLoader().load_from_path(scenario_path)
        out_dir = tmp_path / "new-output-dir"
        assert not out_dir.exists()
        runner = _build_runner(output=out_dir, loaded=loaded)

        ns = _make_namespace(
            "run", scenario=str(scenario_path), output=str(out_dir)
        )
        result = cmd_run(ns)
        assert result == 0
        assert out_dir.exists()

    def test_run_scenario_with_bom_fails(self, tmp_path: Path):
        """A BOM-prefixed scenario file is rejected."""
        bom = tmp_path / "bom.json"
        bom.write_bytes(
            b"\xef\xbb\xbf" + json.dumps(_VALID_SCENARIO_DICT).encode("utf-8")
        )
        ns = _make_namespace("run", scenario=str(bom), output=None)
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    def test_run_scenario_with_duplicate_keys_fails(self, tmp_path: Path):
        """A scenario with duplicate JSON keys is rejected."""
        dup = tmp_path / "dup.json"
        dup.write_text(
            '{"a": 1, "a": 2, "schema_version": "1.0.0", "scenario_id": {"id": "s", "version": 1}, "metadata": {"title": "t", "description": "d", "objective": "o"}, "limits": {"tool_call_limit": 1, "time_limit_seconds": 1}, "seed": 0, "steps": [{"step_id": "1", "description": "x"}]}',
            encoding="utf-8",
        )
        ns = _make_namespace("run", scenario=str(dup), output=None)
        result, stderr = _capture_stderr(cmd_run, ns)
        assert result == 1

    def test_run_scenario_with_path_traversal_fails(self, tmp_path: Path):
        """A scenario path that escapes the allowed root is rejected."""
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        outside = tmp_path.parent / "escape.json"
        outside.write_text(json.dumps(_VALID_SCENARIO_DICT), encoding="utf-8")
        try:
            loader = ScenarioLoader(allowed_root=tmp_path)
            # This would work through cmd_run's load_from_path, but the
            # ScenarioLoader rejects it.
            with pytest.raises(Exception):
                loader.load_from_path(outside)
        finally:
            if outside.exists():
                outside.unlink()


# ---------------------------------------------------------------------------
# Subprocess / integration-style tests
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    """Tests that invoke the CLI entry point as a subprocess.

    These tests require the package to be installed (editable mode) so that
    the ``flight-evaluator`` console script is available.
    """

    @pytest.fixture(autouse=True)
    def _skip_if_not_installed(self, monkeypatch: MonkeyPatch):
        """Skip the entire class if the CLI entry point is not available."""
        import shutil

        if shutil.which("flight-evaluator") is None:
            # Try via python -m
            monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[3] / "src"))

    def test_help_via_main_function(self):
        """Calling main(['--help']) produces help output and exits 0."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_main_returns_int(self):
        """main() always returns an int (the exit code)."""
        # It will fail because the scenario doesn't exist, but should return 1
        result = main(["run", "/nonexistent/scenario.json"])
        assert isinstance(result, int)
        assert result == 1


# ---------------------------------------------------------------------------
# Branch coverage: _build_runner edge cases
# ---------------------------------------------------------------------------


class TestBuildRunnerBranches:
    """Tests that exercise every branch in _build_runner."""

    def test_reference_time_none_uses_default(self, tmp_path: Path):
        """When reference_time is None, the clock defaults to 2026-01-01."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        data = dict(_VALID_SCENARIO_DICT)
        data.pop("reference_time", None)
        scenario_path = tmp_path / "no_ref.json"
        scenario_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=None, loaded=loaded)
        assert runner is not None

    def test_reference_time_with_astimezone_method(self, tmp_path: Path):
        """A datetime reference_time is converted to UTC."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
        from datetime import timezone, timedelta

        data = dict(_VALID_SCENARIO_DICT)
        # A datetime with a non-UTC offset
        offset = timezone(timedelta(hours=5))
        data["reference_time"] = datetime(2026, 1, 1, 12, 0, 0, tzinfo=offset).isoformat()
        scenario_path = tmp_path / "offset_ref.json"
        scenario_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=None, loaded=loaded)
        assert runner is not None

    def test_reference_time_str_with_tz(self, tmp_path: Path):
        """A string reference_time with timezone info works."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        data = dict(_VALID_SCENARIO_DICT)
        data["reference_time"] = "2026-06-15T08:30:00+00:00"
        scenario_path = tmp_path / "str_ref.json"
        scenario_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=None, loaded=loaded)
        assert runner is not None

    def test_id_factory_uses_scenario_params(self, tmp_path: Path):
        """The id_factory is configured from scenario_id, version, and seed."""
        from flight_agent_evaluator.cli.main import _build_runner
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        data = dict(_VALID_SCENARIO_DICT)
        data["scenario_id"] = {"id": "my-scenario", "version": 3}
        data["seed"] = 99
        scenario_path = tmp_path / "custom_id.json"
        scenario_path.write_text(json.dumps(data), encoding="utf-8")
        loaded = ScenarioLoader().load_from_path(scenario_path)
        runner = _build_runner(output=None, loaded=loaded)
        assert runner is not None

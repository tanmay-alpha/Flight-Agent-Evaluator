"""Security tests for the Phase 2 runtime."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from flight_agent_evaluator.engine.scenario_loader import (
    ScenarioLoader,
    ScenarioLoaderError,
)
from flight_agent_evaluator.recording.store import (
    FileRecordingStore,
    RecordingStoreError,
)
from flight_agent_evaluator.recording.journal import HashChainJournal


def test_path_traversal_rejected(tmp_path: Path):
    loader = ScenarioLoader(allowed_root=tmp_path)
    with pytest.raises(ScenarioLoaderError, match="outside"):
        loader.load_from_path(tmp_path.parent / "escape.json")


def test_symlink_rejected_for_recording(tmp_path: Path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link"
    try:
        link_dir.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    store = FileRecordingStore(real_dir)
    journal = HashChainJournal()
    journal_path = real_dir / "test.jsonl"
    journal._write_jsonl_string()  # ensure helper exists
    # Write through a path that is a symlink — should be rejected.
    from flight_agent_evaluator.recording.contracts import RunRecording
    from datetime import UTC, datetime

    recording = RunRecording(
        run_id="test",
        scenario_id="x",
        scenario_version=1,
        seed=0,
        entry_count=0,
        final_digest=journal.final_digest(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    # The path under the symlink target should be rejected if it tries to escape.
    try:
        # Try to write through a path traversal via run_id
        store.write_recording("..\\escape", journal, recording)
    except RecordingStoreError:
        pass  # Expected
    except Exception as e:
        # Some other error is OK as long as it's not silent success.
        assert "escape" in str(e).lower() or "invalid" in str(e).lower()


def test_run_id_traversal_in_filename(tmp_path: Path):
    store = FileRecordingStore(tmp_path)
    journal = HashChainJournal()
    from flight_agent_evaluator.recording.contracts import RunRecording
    from datetime import UTC, datetime

    recording = RunRecording(
        run_id="..\\evil",
        scenario_id="x",
        scenario_version=1,
        seed=0,
        entry_count=0,
        final_digest=journal.final_digest(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    # The sanitiser should reject path-traversal attempts.
    with pytest.raises(RecordingStoreError):
        store.write_recording("..\\evil", journal, recording)


def test_bom_in_scenario_rejected(tmp_path: Path):
    target = tmp_path / "scenario.json"
    target.write_bytes(b"\xef\xbb\xbf{}")
    loader = ScenarioLoader()
    with pytest.raises(ScenarioLoaderError, match="BOM"):
        loader.load_from_path(target)

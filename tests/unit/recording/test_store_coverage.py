"""Unit tests for FileRecordingStore and bundle verification."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_agent_evaluator.recording.contracts import (
    JournalEntry,
    RecordingBundleManifest,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import (
    FileRecordingStore,
    RecordingBundleIncompleteError,
    RecordingIntegrityError,
    RecordingPathError,
)


def _make_sample_bundle(
    run_id: str,
) -> tuple[HashChainJournal, RunRecording, RecordingBundleManifest]:
    uid = uuid.UUID(run_id)
    journal = HashChainJournal()
    entry = journal.append(
        JournalEntry(
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uid,
            correlation_id="c1",
            time=datetime.now(UTC),
            payload={"test": True},
            prev_hash="0" * 64,
            hash="",
        )
    )

    final_digest = journal.final_digest()
    rec = RunRecording(
        run_id=uid,
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        seed=42,
        entry_count=1,
        final_digest=final_digest,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        tool_calls_made=0,
    )

    j_bytes = journal.to_jsonl_string().encode("utf-8")
    m_bytes = (rec.model_dump_json(indent=2) + "\n").encode("utf-8")

    manifest = RecordingBundleManifest(
        run_id=run_id,
        journal_file=f"{run_id}.jsonl",
        journal_bytes_sha256=hashlib.sha256(j_bytes).hexdigest(),
        journal_chain_digest=final_digest,
        journal_entry_count=1,
        metadata_file=f"{run_id}.meta.json",
        metadata_bytes_sha256=hashlib.sha256(m_bytes).hexdigest(),
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        scenario_digest="a" * 64,
        agent_id="oracle",
        semantic_recording_digest="b" * 64,
    )

    return journal, rec, manifest


def test_sanitise_run_id_errors(tmp_path: Path):
    store = FileRecordingStore(tmp_path)
    with pytest.raises(RecordingPathError, match="must not be empty"):
        store.resolve_safe_path("")

    with pytest.raises(RecordingPathError, match="Invalid characters"):
        store.resolve_safe_path("run\x00123")

    with pytest.raises(RecordingPathError, match="Path separators"):
        store.resolve_safe_path("../secret")

    with pytest.raises(RecordingPathError, match="Path separators"):
        store.resolve_safe_path("sub/folder")

    with pytest.raises(RecordingPathError, match="Invalid run_id"):
        store.resolve_safe_path("..")


def test_write_and_read_bundle(tmp_path: Path):
    store = FileRecordingStore(tmp_path)
    run_id = str(uuid.uuid4())
    journal, rec, manifest = _make_sample_bundle(run_id)

    store.write_recording(run_id, journal, rec, manifest)
    assert store.root == tmp_path

    # Read back bundle
    j_read, r_read, m_read = store.read_bundle(run_id, strict=True)
    assert j_read.entry_count == 1
    assert str(r_read.run_id) == run_id
    assert m_read is not None
    assert m_read.run_id == run_id


def test_read_bundle_tampered(tmp_path: Path):
    store = FileRecordingStore(tmp_path)
    run_id = str(uuid.uuid4())
    journal, rec, manifest = _make_sample_bundle(run_id)
    store.write_recording(run_id, journal, rec, manifest)

    # Tamper journal file
    j_path = store.resolve_safe_path(run_id, ".jsonl")
    j_path.write_bytes(b"tampered content\n")

    with pytest.raises(RecordingIntegrityError, match="Journal byte digest mismatch"):
        store.read_bundle(run_id, strict=True)


def test_read_bundle_missing_files(tmp_path: Path):
    store = FileRecordingStore(tmp_path)
    run_id = str(uuid.uuid4())
    with pytest.raises(RecordingBundleIncompleteError):
        store.read_bundle(run_id)

    with pytest.raises(RecordingBundleIncompleteError):
        store.read_recording(run_id)

    with pytest.raises(RecordingBundleIncompleteError):
        store.read_recording_summary(run_id)

    with pytest.raises(RecordingBundleIncompleteError):
        store.read_bundle_manifest(run_id)

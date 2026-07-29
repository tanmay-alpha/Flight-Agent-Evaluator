"""Tests for recording.journal."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_agent_evaluator.recording.contracts import JournalEntry
from flight_agent_evaluator.recording.journal import (
    HashChainJournal,
    JournalVerificationError,
    compute_canonical_entry_hash,
)


def _make_entry(
    seq: int,
    run_id="00000000-0000-0000-0000-000000000001",
    time=None,
    payload=None,
    prev_hash="",
    etype="run_started",
):
    return JournalEntry(
        seq=seq,
        id=uuid.UUID(f"11111111-0000-0000-0000-{seq:012d}"),
        type=etype,
        run_id=run_id,
        correlation_id="corr-001",
        time=time or datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC),
        payload=payload or {"x": 1},
        prev_hash=prev_hash,
        hash="placeholder",
    )


def _build_journal(n: int = 2) -> HashChainJournal:
    """Build a journal of *n* entries using the append API."""
    journal = HashChainJournal()
    for seq in range(1, n + 1):
        etype = "run_started" if seq == 1 else "tool_call"
        expected_prev = "" if seq == 1 else journal.entries[-1].hash
        journal.append(_make_entry(seq=seq, etype=etype, prev_hash=expected_prev))
    return journal


class TestComputeCanonicalEntryHash:
    def test_deterministic(self):
        entry = _make_entry(seq=1)
        h1 = compute_canonical_entry_hash(entry)
        h2 = compute_canonical_entry_hash(entry)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_seq_different_hash(self):
        e1 = _make_entry(seq=1)
        e2 = _make_entry(seq=2)
        h1 = compute_canonical_entry_hash(e1)
        h2 = compute_canonical_entry_hash(e2)
        assert h1 != h2

    def test_hash_excludes_hash_field(self):
        """Mutating the hash field must not change the canonical hash."""
        e = _make_entry(seq=1)
        h_before = compute_canonical_entry_hash(e)
        e2 = e.model_copy(update={"hash": "different-value"})
        assert compute_canonical_entry_hash(e2) == h_before

    def test_different_prev_hash_produces_different_hash(self):
        e1 = _make_entry(seq=2, prev_hash="a" * 64)
        e2 = _make_entry(seq=2, prev_hash="b" * 64)
        assert compute_canonical_entry_hash(e1) != compute_canonical_entry_hash(e2)


class TestHashChainJournal:
    def test_append_assigns_sequence_and_id_and_hash(self):
        journal = HashChainJournal()
        for seq in range(1, 4):
            journal.append(_make_entry(seq=seq))
        assert journal.entry_count == 3
        for i, e in enumerate(journal.entries):
            assert e.seq == i + 1
            assert len(e.hash) == 64

    def test_verify_valid_chain_passes(self):
        journal = _build_journal(n=2)
        assert journal.verify() is True

    def test_final_digest_is_hex_64(self):
        journal = _build_journal(n=2)
        digest = journal.final_digest()
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_final_digest_is_deterministic(self):
        j1 = _build_journal(n=2)
        j2 = _build_journal(n=2)
        assert j1.final_digest() == j2.final_digest()

    def test_tampered_payload_detected(self):
        journal = _build_journal(n=2)
        target = Path("__tamper_test__.jsonl")
        try:
            journal.write_jsonl(target)
            lines = target.read_text(encoding="utf-8").splitlines()
            first = json.loads(lines[0])
            first["payload"] = {"x": 999}
            lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            loaded = HashChainJournal.read_jsonl(target)
            with pytest.raises(JournalVerificationError):
                loaded.verify()
        finally:
            if target.exists():
                target.unlink()

    def test_broken_chain_detected(self):
        journal = _build_journal(n=2)
        target = Path("__chain_break_test__.jsonl")
        try:
            journal.write_jsonl(target)
            lines = target.read_text(encoding="utf-8").splitlines()
            entry2 = json.loads(lines[1])
            entry2["prev_hash"] = "0" * 64
            lines[1] = json.dumps(entry2, sort_keys=True, separators=(",", ":"))
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            loaded = HashChainJournal.read_jsonl(target)
            with pytest.raises(JournalVerificationError):
                loaded.verify()
        finally:
            if target.exists():
                target.unlink()

    def test_sequence_gap_detected(self):
        target = Path("__seq_gap_test__.jsonl")
        try:
            j1 = _build_journal(n=2)
            lines = j1._write_jsonl_string().rstrip("\n").splitlines()
            first_obj = json.loads(lines[0])
            third_obj = first_obj.copy()
            third_obj["seq"] = 3
            third_obj["id"] = str(
                uuid.UUID("11111111-0000-0000-0000-000000000003")
            )
            third_obj["time"] = third_obj["time"].replace("10:00:00", "10:00:02")
            third_line = json.dumps(third_obj, sort_keys=True, separators=(",", ":"))
            target.write_text(lines[0] + "\n" + third_line + "\n", encoding="utf-8")
            loaded = HashChainJournal.read_jsonl(target)
            with pytest.raises(JournalVerificationError, match="gap"):
                loaded.verify()
        finally:
            if target.exists():
                target.unlink()

    def test_empty_journal_digest(self):
        j = HashChainJournal()
        d = j.final_digest()
        assert len(d) == 64

    def test_empty_journal_verifies(self):
        j = HashChainJournal()
        assert j.verify() is True


class TestJournalRoundTrip:
    def test_jsonl_roundtrip(self, tmp_path: Path):
        journal = _build_journal(n=2)
        target = tmp_path / "recording.jsonl"
        journal.write_jsonl(target)
        loaded = HashChainJournal.read_jsonl(target)
        assert loaded.verify()
        assert loaded.entry_count == 2
        assert loaded.final_digest() == journal.final_digest()

    def test_jsonl_lines_are_canonical(self, tmp_path: Path):
        journal = _build_journal(n=2)
        target = tmp_path / "recording.jsonl"
        journal.write_jsonl(target)
        lines = target.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert list(obj.keys()) == sorted(obj.keys())
            canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
            assert line == canonical


def test_empty_hash_is_64_zeros():
    assert "0" * 64 == "0" * 64

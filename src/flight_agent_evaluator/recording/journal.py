"""Append-only hash-chained journal for run recordings.

Each entry's hash is computed from its canonical representation (all
fields except ``hash``, sorted keys, ISO 8601 UTC timestamps, no
whitespace variation). Entries are linked via ``prev_hash``. Any
modification to a recorded entry invalidates the chain from that point
forward.

No cryptographic authentication is provided. SHA-256 detects alteration
but does not prove who created a recording.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from flight_agent_evaluator.recording.contracts import JournalEntry

EMPTY_HASH: Final[str] = "0" * 64


def _canonicalise_payload(obj: dict[str, object]) -> str:
    """Serialise *obj* as canonical JSON (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_canonical_entry_hash(entry: JournalEntry) -> str:
    """Compute the SHA-256 hex digest of an entry's canonical form.

    The ``hash`` field is excluded so the digest is stable across recomputes.
    """
    data = entry.model_dump(mode="json", exclude={"hash"})
    payload_str = _canonicalise_payload(data)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


class JournalVerificationError(Exception):
    """Raised when a journal hash chain fails verification."""


class HashChainJournal:
    """Append-only hash-chained journal of journal entries.

    The journal assigns sequence numbers, links entries via ``prev_hash``,
    and verifies the chain on demand. It never writes to disk; persistence
    is delegated to a recording store.
    """

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def append(self, entry: JournalEntry) -> JournalEntry:
        """Append an entry to the journal.

        The ``hash`` field is replaced with a freshly computed value. The
        ``seq`` field must be one greater than the current entry count.
        The ``prev_hash`` field must match the last entry's ``hash`` or
        be empty/zeros for the first entry.
        """
        expected_prev = self._entries[-1].hash if self._entries else ""
        expected_seq = self.entry_count + 1
        if entry.seq != expected_seq:
            raise JournalVerificationError(f"Expected sequence {expected_seq}, got {entry.seq}")
        if entry.prev_hash not in (expected_prev, ""):
            raise JournalVerificationError(
                f"prev_hash mismatch at seq={entry.seq}: "
                f"expected {expected_prev}, got {entry.prev_hash}"
            )
        # Recompute hash.
        h = compute_canonical_entry_hash(entry)
        filled = entry.model_copy(update={"hash": h})
        self._entries.append(filled)
        return filled

    def append_event(
        self,
        entry_type: str,
        run_id: str,
        correlation_id: str,
        time: object,
        payload: dict[str, object],
        entry_id: object | None = None,
    ) -> JournalEntry:
        """Append a typed event with proper seq/hash chaining.

        The journal assigns the seq from the current entry count,
        computes the prev_hash from the previous entry (or ""),
        and then re-hashes the entry.

        If ``entry_id`` is not provided, a deterministic UUID is derived
        from the entry's position in the chain. Callers that have a
        deterministic ID factory should pass the result here so that
        the recording is fully reproducible.
        """
        import uuid as _uuid

        seq = self.entry_count + 1
        prev_hash = self._entries[-1].hash if self._entries else ""
        if entry_id is None:
            entry_id = _uuid.UUID(hashlib.sha256(f"{seq}:{entry_type}".encode()).hexdigest()[:32])
        draft = JournalEntry(
            seq=seq,
            id=entry_id,
            type=entry_type,
            run_id=_uuid.UUID(run_id) if isinstance(run_id, str) else run_id,
            correlation_id=correlation_id,
            time=time,
            payload=payload,
            prev_hash=prev_hash,
            hash="0" * 64,
        )
        h = compute_canonical_entry_hash(draft)
        filled = draft.model_copy(update={"hash": h})
        self._entries.append(filled)
        return filled

    def append_raw(self, entry: JournalEntry) -> None:
        """Append an entry without re-validating seq/prev_hash.

        This is intended for loading from disk where each entry's hash is
        already filled in. Use :meth:`verify` after to confirm integrity.
        """
        self._entries.append(entry)

    @classmethod
    def from_entries(cls, entries: Iterable[JournalEntry]) -> HashChainJournal:
        """Construct a journal from an iterable of pre-built entries."""
        j = cls()
        for e in entries:
            j.append_raw(e)
        return j

    def to_jsonl_string(self) -> str:
        """Serialise the journal to a single JSON Lines string."""
        lines = []
        for entry in self._entries:
            data = entry.model_dump(mode="json")
            lines.append(_canonicalise_payload(data))
        return "\n".join(lines) + "\n"

    def write_jsonl(self, path: Path) -> None:
        """Write the journal as canonical JSON Lines."""
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for entry in self._entries:
                data = entry.model_dump(mode="json")
                line = _canonicalise_payload(data)
                f.write(line)
                f.write("\n")

    def final_digest(self) -> str:
        """Compute a single 64-character hex digest identifying the entire
        recording as the SHA-256 of the canonical concatenation of all
        entry hashes joined by newline with a trailing newline.
        """
        if not self._entries:
            return hashlib.sha256(b"").hexdigest()
        joined = "\n".join(e.hash for e in self._entries) + "\n"
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def verify(self) -> bool:
        """Verify the entire chain. Returns True on success.

        Raises ``JournalVerificationError`` on failure.
        """
        prev = ""
        for idx, entry in enumerate(self._entries, start=1):
            if entry.seq != idx:
                raise JournalVerificationError(f"Sequence gap: expected {idx}, got {entry.seq}")
            if entry.prev_hash != prev:
                raise JournalVerificationError(
                    f"Chain break at seq={entry.seq}: prev_hash mismatch"
                )
            expected_hash = compute_canonical_entry_hash(entry)
            if entry.hash != expected_hash:
                raise JournalVerificationError(
                    f"Hash mismatch at seq={entry.seq}: expected {expected_hash}, got {entry.hash}"
                )
            prev = entry.hash
        return True

    @classmethod
    def read_jsonl(cls, path: Path) -> HashChainJournal:
        """Load a journal from canonical JSON Lines."""
        j = cls()
        with path.open("r", encoding="utf-8", newline="\n") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                obj = json.loads(line)
                j.append_raw(JournalEntry.model_validate(obj))
        return j

"""File-based recording store for Phase 2.

Writes journals atomically to a target directory. Files are named by
``run_id``. The store never reveals caller-controlled path components
outside the target directory. Symlinks are not followed for writes.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from flight_agent_evaluator.recording.contracts import RunRecording
from flight_agent_evaluator.recording.journal import HashChainJournal


class RecordingStoreError(Exception):
    """Raised when writing a recording fails."""


class FileRecordingStore:
    """Persist run recordings to a target directory.

    Each recording is written as:

    - ``<run_id>.jsonl`` — the journal entries.
    - ``<run_id>.meta.json`` — the ``RunRecording`` metadata.
    """

    def __init__(self, target_directory: Path) -> None:
        self._target = Path(target_directory)
        self._target.mkdir(parents=True, exist_ok=True)

    def write_recording(
        self, run_id: str, journal: HashChainJournal, recording: RunRecording
    ) -> Path:
        """Write a journal and its metadata atomically to the target directory."""
        stem = self._sanitise_run_id(run_id)
        journal_path = self._target / f"{stem}.jsonl"
        meta_path = self._target / f"{stem}.meta.json"

        self._write_atomic(journal_path, journal.to_jsonl_string())
        self._write_atomic(
            meta_path,
            recording.model_dump_json(indent=2) + "\n",
        )
        return journal_path

    def read_recording(self, run_id: str) -> HashChainJournal:
        """Read a journal from the target directory."""
        stem = self._sanitise_run_id(run_id)
        path = self._target / f"{stem}.jsonl"
        if not path.is_file():
            raise RecordingStoreError(f"Recording not found: {run_id!r}")
        return HashChainJournal.read_jsonl(path)

    def _sanitise_run_id(self, run_id: str) -> str:
        """Return a safe filename stem for the run ID.

        Rejects path traversal attempts.
        """
        if not run_id:
            raise RecordingStoreError("run_id must not be empty")
        # Reject anything that has a path separator or is "."/"..".
        if "/" in run_id or "\\" in run_id:
            raise RecordingStoreError(f"Invalid run_id: {run_id!r}")
        stem = run_id
        if stem in (".", ".."):
            raise RecordingStoreError(f"Invalid run_id: {run_id!r}")
        # Additional safety: must be a single path component.
        if Path(run_id).name != run_id:
            raise RecordingStoreError(f"Invalid run_id: {run_id!r}")
        return stem

    def _write_atomic(self, path: Path, content: str) -> None:
        """Write *content* to *path* atomically via temp-file rename."""
        target = self._resolve_safe(path)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp_path: str | None = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(parent), prefix=".tmp-", suffix=".partial")
            tmp_path = tmp
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                os.replace(tmp, str(target))
                tmp_path = None
            finally:
                if tmp_path is not None:
                    import contextlib

                    with contextlib.suppress(OSError):
                        os.unlink(tmp_path)
        except OSError as exc:
            raise RecordingStoreError(f"Failed to write {target}: {exc}") from exc

    def _resolve_safe(self, path: Path) -> Path:
        """Resolve *path* without following symlinks; reject if it escapes."""
        if path.is_symlink():
            raise RecordingStoreError(f"Symlink not allowed for recording path: {path}")
        try:
            target_resolved = self._target.resolve(strict=False)
            # ``strict=False`` so a missing target doesn't raise.
            path_resolved = path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise RecordingStoreError(f"Failed to resolve path: {exc}") from exc
        try:
            path_resolved.relative_to(target_resolved)
        except ValueError as exc:
            raise RecordingStoreError(f"Recording path escapes target directory: {path}") from exc
        return path_resolved

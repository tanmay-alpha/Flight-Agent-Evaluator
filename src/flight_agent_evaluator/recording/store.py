"""File-based recording store for Phase 2 and Layer 4.

Writes journals, summaries, and bundle manifests atomically to a target directory.
Files are named by ``run_id``. The store never resolves caller-controlled path components
outside the target directory. Symlinks and path traversals are rejected.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from pathlib import Path

from flight_agent_evaluator.recording.contracts import (
    RecordingBundleManifest,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import (
    HashChainJournal,
    JournalReadLimits,
    JournalVerificationError,
)


class RecordingStoreError(Exception):
    """Base error for recording store operations."""


class RecordingPathError(RecordingStoreError):
    """Raised when a path traversal, symlink, or unsafe path is encountered."""


class RecordingIntegrityError(RecordingStoreError):
    """Raised when a recording fails cryptographic hash or cross-check verification."""


class RecordingBundleIncompleteError(RecordingStoreError):
    """Raised when required recording bundle files are missing."""


class FileRecordingStore:
    """Persist and read run recordings and bundle manifests.

    Each complete recording bundle consists of:
    - ``<run_id>.jsonl`` — the append-only hash-chained journal entries.
    - ``<run_id>.meta.json`` — the ``RunRecording`` metadata.
    - ``<run_id>.bundle.json`` — the ``RecordingBundleManifest`` cross-binding.
    """

    def __init__(self, target_directory: Path | str) -> None:
        self._target = Path(target_directory)
        self._target.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """Target root directory."""
        return self._target

    def _sanitise_run_id(self, run_id: str) -> str:
        """Return a safe filename stem for the run ID.

        Strictly rejects path traversal attempts, absolute paths, drive prefixes,
        UNC paths, null bytes, and path separators.
        """
        if not run_id or not isinstance(run_id, str):
            raise RecordingPathError("run_id must not be empty")
        if "\x00" in run_id or "\r" in run_id or "\n" in run_id or "\t" in run_id:
            raise RecordingPathError(f"Invalid characters in run_id: {run_id!r}")
        if "/" in run_id or "\\" in run_id or ":" in run_id:
            raise RecordingPathError(f"Path separators or drive indicators in run_id: {run_id!r}")
        stem = run_id.strip()
        if stem in (".", "..") or not stem:
            raise RecordingPathError(f"Invalid run_id: {run_id!r}")
        if Path(stem).name != stem:
            raise RecordingPathError(f"Invalid run_id path component: {run_id!r}")
        return stem

    def resolve_safe_path(self, run_id: str, suffix: str = ".jsonl") -> Path:
        """Resolve a safe path inside the target directory."""
        stem = self._sanitise_run_id(run_id)
        candidate = self._target / f"{stem}{suffix}"
        return self._resolve_safe(candidate)

    def _resolve_safe(self, path: Path) -> Path:
        """Resolve *path* without following symlinks; reject if it escapes."""
        if path.is_symlink():
            raise RecordingPathError(f"Symlinks are not allowed for recording paths: {path}")
        try:
            target_resolved = self._target.resolve(strict=False)
            path_resolved = path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise RecordingPathError(f"Failed to resolve path: {exc}") from exc

        try:
            path_resolved.relative_to(target_resolved)
        except ValueError as exc:
            raise RecordingPathError(f"Recording path escapes target directory: {path}") from exc
        return path_resolved

    def _write_atomic(self, path: Path, content_bytes: bytes) -> None:
        """Write *content_bytes* to *path* atomically via temp-file rename."""
        target = self._resolve_safe(path)
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        tmp_path: str | None = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(parent), prefix=".tmp-", suffix=".partial")
            tmp_path = tmp
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(content_bytes)
                os.replace(tmp, str(target))
                tmp_path = None
            finally:
                if tmp_path is not None:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_path)
        except OSError as exc:
            raise RecordingStoreError(f"Failed to write {target}: {exc}") from exc

    def write_recording(
        self,
        run_id: str,
        journal: HashChainJournal,
        recording: RunRecording,
        manifest: RecordingBundleManifest | None = None,
    ) -> Path:
        """Write a journal, its metadata, and optional bundle manifest atomically."""
        stem = self._sanitise_run_id(run_id)
        journal_path = self._target / f"{stem}.jsonl"
        meta_path = self._target / f"{stem}.meta.json"
        bundle_path = self._target / f"{stem}.bundle.json"

        journal_bytes = journal.to_jsonl_string().encode("utf-8")
        meta_bytes = (recording.model_dump_json(indent=2) + "\n").encode("utf-8")

        self._write_atomic(journal_path, journal_bytes)
        self._write_atomic(meta_path, meta_bytes)

        if manifest is not None:
            manifest_bytes = (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
            self._write_atomic(bundle_path, manifest_bytes)

        return journal_path

    def read_recording(
        self, run_id: str, limits: JournalReadLimits | None = None
    ) -> HashChainJournal:
        """Read and verify a journal from the target directory."""
        path = self.resolve_safe_path(run_id, ".jsonl")
        if not path.is_file():
            raise RecordingBundleIncompleteError(f"Recording journal not found: {run_id!r}")
        try:
            return HashChainJournal.read_verified_jsonl(path, limits=limits)
        except JournalVerificationError as exc:
            raise RecordingIntegrityError(
                f"Journal verification failed for {run_id!r}: {exc}"
            ) from exc

    def read_recording_summary(self, run_id: str) -> RunRecording:
        """Read RunRecording summary metadata from the target directory."""
        path = self.resolve_safe_path(run_id, ".meta.json")
        if not path.is_file():
            raise RecordingBundleIncompleteError(f"Recording summary not found: {run_id!r}")
        try:
            return RunRecording.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RecordingIntegrityError(
                f"Invalid recording metadata for {run_id!r}: {exc}"
            ) from exc

    def read_bundle_manifest(self, run_id: str) -> RecordingBundleManifest:
        """Read RecordingBundleManifest from the target directory."""
        path = self.resolve_safe_path(run_id, ".bundle.json")
        if not path.is_file():
            raise RecordingBundleIncompleteError(f"Recording bundle manifest not found: {run_id!r}")
        try:
            return RecordingBundleManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RecordingIntegrityError(f"Invalid bundle manifest for {run_id!r}: {exc}") from exc

    def read_bundle(
        self, run_id: str, strict: bool = True
    ) -> tuple[HashChainJournal, RunRecording, RecordingBundleManifest | None]:
        """Read and verify a complete recording bundle.

        In strict mode, validates raw byte hashes against the bundle manifest,
        cross-checks metadata fields with journal contents, and ensures full
        internal consistency.
        """
        stem = self._sanitise_run_id(run_id)
        journal_path = self.resolve_safe_path(stem, ".jsonl")
        meta_path = self.resolve_safe_path(stem, ".meta.json")
        bundle_path = self.resolve_safe_path(stem, ".bundle.json")

        if not journal_path.is_file() or not meta_path.is_file():
            raise RecordingBundleIncompleteError(f"Recording bundle incomplete for {run_id!r}")

        manifest: RecordingBundleManifest | None = None
        if bundle_path.is_file():
            manifest = self.read_bundle_manifest(stem)
        elif strict:
            raise RecordingBundleIncompleteError(
                f"Strict bundle reading requires .bundle.json manifest for {run_id!r}"
            )

        # Raw byte verification against manifest if available
        if manifest is not None:
            j_bytes = journal_path.read_bytes()
            m_bytes = meta_path.read_bytes()
            j_sha = hashlib.sha256(j_bytes).hexdigest()
            m_sha = hashlib.sha256(m_bytes).hexdigest()

            if j_sha != manifest.journal_bytes_sha256:
                raise RecordingIntegrityError(
                    f"Journal byte digest mismatch: expected {manifest.journal_bytes_sha256}, got {j_sha}"
                )
            if m_sha != manifest.metadata_bytes_sha256:
                raise RecordingIntegrityError(
                    f"Metadata byte digest mismatch: expected {manifest.metadata_bytes_sha256}, got {m_sha}"
                )

        journal = self.read_recording(stem)
        recording = self.read_recording_summary(stem)

        # Cross-field checks
        if str(recording.run_id) != stem:
            raise RecordingIntegrityError(
                f"Run ID mismatch in metadata: expected {stem}, got {recording.run_id}"
            )
        if journal.entry_count != recording.entry_count:
            raise RecordingIntegrityError(
                f"Entry count mismatch: journal={journal.entry_count}, metadata={recording.entry_count}"
            )
        if journal.final_digest() != recording.final_digest:
            raise RecordingIntegrityError(
                f"Final digest mismatch: journal={journal.final_digest()}, metadata={recording.final_digest}"
            )

        if manifest is not None:
            if manifest.run_id != stem:
                raise RecordingIntegrityError(
                    f"Run ID mismatch in manifest: expected {stem}, got {manifest.run_id}"
                )
            if manifest.journal_entry_count != journal.entry_count:
                raise RecordingIntegrityError(
                    f"Entry count mismatch in manifest: expected {journal.entry_count}, got {manifest.journal_entry_count}"
                )
            if manifest.journal_chain_digest != journal.final_digest():
                raise RecordingIntegrityError(
                    f"Chain digest mismatch in manifest: expected {journal.final_digest()}, got {manifest.journal_chain_digest}"
                )

        return journal, recording, manifest

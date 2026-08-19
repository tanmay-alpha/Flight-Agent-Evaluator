"""Replay and verification engine for run recordings.

Provides:
- **playback**: reads and formats verified recording contents without re-execution.
- **verification**: verifies recording integrity, reconstructs exact provenance,
  re-executes deterministically in an isolated environment, projects semantic event streams,
  and compares observable behaviour event-by-event with typed divergence reporting.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from flight_agent_evaluator.recording.contracts import (
    BehaviourVerificationStatus,
    RecordingBundleManifest,
    RecordingIntegrityStatus,
    ReplayReport,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import (
    HashChainJournal,
    JournalVerificationError,
)
from flight_agent_evaluator.recording.store import (
    FileRecordingStore,
    RecordingIntegrityError,
    RecordingStoreError,
)
from flight_agent_evaluator.replay.comparator import (
    SemanticDivergenceRecord,
    SemanticDivergenceType,
    SemanticReplayComparator,
)
from flight_agent_evaluator.replay.projection import (
    compute_semantic_recording_digest,
    project_semantic_event,
)
from flight_agent_evaluator.replay.provenance import (
    ReplayExecutionFactory,
    ReplayProvenanceError,
    ReplayProvenanceMismatchError,
    ReplayUnavailableError,
    extract_provenance,
)

logger = logging.getLogger(__name__)


class ReplayEngine:
    """Replay engine orchestrating recording playback and deterministic verification."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else Path(".recordings")
        self._store = FileRecordingStore(self._root)

    @property
    def store(self) -> FileRecordingStore:
        return self._store

    def playback(self, run_id: str, verify_integrity: bool = True) -> dict[str, Any]:
        """Replay a recording in playback mode.

        Validates recording integrity by default before returning entries.
        """
        # Strictly route through FileRecordingStore for path safety
        if verify_integrity:
            journal = self._store.read_recording(run_id)
        else:
            path = self._store.resolve_safe_path(run_id, ".jsonl")
            journal = HashChainJournal.read_unverified_jsonl(path)

        return {
            "run_id": run_id,
            "entries": [e.model_dump(mode="json") for e in journal.entries],
            "digest": journal.final_digest(),
            "integrity_verified": verify_integrity,
        }

    def verify(
        self,
        run_id: str,
        scenario_path: Path | None = None,
        provider: Any = None,
        driver: Any = None,
        model_exchange_manifest: Any = None,
        strict_bundle: bool = False,
    ) -> ReplayReport:
        """Verify recording integrity and deterministic behavioural equivalence."""
        stem = self._store._sanitise_run_id(run_id)

        # 1. Load and verify recording artifacts from store
        journal: HashChainJournal | None = None
        recording: RunRecording | None = None
        manifest: RecordingBundleManifest | None = None
        integrity_status = RecordingIntegrityStatus.UNAVAILABLE
        divergences: list[SemanticDivergenceRecord] = []

        try:
            journal, recording, manifest = self._store.read_bundle(stem, strict=strict_bundle)
            integrity_status = RecordingIntegrityStatus.VERIFIED
        except RecordingIntegrityError as exc:
            integrity_status = RecordingIntegrityStatus.TAMPERED
            divergences.append(
                SemanticDivergenceRecord(
                    sequence=1,
                    kind=SemanticDivergenceType.RECORDING_TAMPERED,
                    detail=f"Recording integrity check failed: {exc}",
                )
            )
        except RecordingStoreError:
            # Try loading unverified journal if available
            try:
                path = self._store.resolve_safe_path(stem, ".jsonl")
                if path.is_file():
                    journal = HashChainJournal.read_unverified_jsonl(path)
                    try:
                        journal.verify()
                        integrity_status = RecordingIntegrityStatus.INCOMPLETE
                    except JournalVerificationError as j_exc:
                        integrity_status = RecordingIntegrityStatus.TAMPERED
                        divergences.append(
                            SemanticDivergenceRecord(
                                sequence=1,
                                kind=SemanticDivergenceType.RECORDING_TAMPERED,
                                detail=f"Journal hash chain broken: {j_exc}",
                            )
                        )
            except Exception as exc:
                integrity_status = RecordingIntegrityStatus.UNAVAILABLE
                divergences.append(
                    SemanticDivergenceRecord(
                        sequence=1,
                        kind=SemanticDivergenceType.RECORDING_TAMPERED,
                        detail=f"Journal unreadable or corrupted: {exc}",
                    )
                )

        final_digest = journal.final_digest() if journal else "0" * 64
        entry_count = journal.entry_count if journal else 0

        # If recording integrity is tampered or unavailable, fail closed immediately
        if (
            integrity_status != RecordingIntegrityStatus.VERIFIED
            and integrity_status != RecordingIntegrityStatus.INCOMPLETE
        ):
            legacy_divergences = tuple(d.to_legacy_divergence() for d in divergences)
            return ReplayReport(
                recording_run_id=stem,
                mode="verification",
                integrity_status=integrity_status,
                behaviour_status=None,
                original_journal_digest=final_digest,
                original_semantic_digest="",
                provenance_status="unavailable",
                divergences=legacy_divergences,
                final_digest=final_digest,
                entry_count=entry_count,
            )

        if journal is None:
            legacy_divergences = tuple(d.to_legacy_divergence() for d in divergences)
            return ReplayReport(
                recording_run_id=stem,
                mode="verification",
                integrity_status=RecordingIntegrityStatus.UNAVAILABLE,
                behaviour_status=None,
                original_journal_digest=final_digest,
                original_semantic_digest="",
                provenance_status="unavailable",
                divergences=legacy_divergences,
                final_digest=final_digest,
                entry_count=entry_count,
            )

        # 2. Extract provenance
        try:
            provenance = extract_provenance(recording, journal, manifest)
            provenance_status: str = "verified"
        except ReplayProvenanceError as exc:
            divergences.append(
                SemanticDivergenceRecord(
                    sequence=1,
                    kind=SemanticDivergenceType.PROVENANCE_MISMATCH,
                    detail=f"Provenance extraction failed: {exc}",
                )
            )
            legacy_divergences = tuple(d.to_legacy_divergence() for d in divergences)
            return ReplayReport(
                recording_run_id=stem,
                mode="verification",
                integrity_status=integrity_status,
                behaviour_status=BehaviourVerificationStatus.UNAVAILABLE,
                original_journal_digest=final_digest,
                original_semantic_digest="",
                provenance_status="unavailable",
                divergences=legacy_divergences,
                final_digest=final_digest,
                entry_count=entry_count,
            )

        # 3. Resolve execution components via factory
        factory = ReplayExecutionFactory()
        try:
            loaded_scenario = factory.resolve_scenario(provenance, explicit_path=scenario_path)
            agent_policy = factory.resolve_agent(
                provenance,
                model_exchange_manifest=model_exchange_manifest,
                custom_driver=driver,
            )
        except (ReplayProvenanceMismatchError, ReplayUnavailableError) as exc:
            if isinstance(exc, ReplayProvenanceMismatchError):
                divergences.append(
                    SemanticDivergenceRecord(
                        sequence=1,
                        kind=SemanticDivergenceType.PROVENANCE_MISMATCH,
                        detail=f"Replay resource mismatch: {exc}",
                    )
                )
            legacy_divergences = tuple(d.to_legacy_divergence() for d in divergences)
            return ReplayReport(
                recording_run_id=stem,
                mode="verification",
                integrity_status=integrity_status,
                behaviour_status=BehaviourVerificationStatus.UNAVAILABLE,
                original_journal_digest=final_digest,
                original_semantic_digest="",
                provenance_status="mismatch"
                if isinstance(exc, ReplayProvenanceMismatchError)
                else "unavailable",
                divergences=legacy_divergences,
                final_digest=final_digest,
                entry_count=entry_count,
            )

        # 4. Project original semantic events
        orig_semantic_events = tuple(project_semantic_event(e) for e in journal.entries)
        orig_semantic_digest = compute_semantic_recording_digest(orig_semantic_events)

        # 5. Re-execute deterministically in isolated temporary directory
        runner = factory.create_runner()
        re_journal: HashChainJournal | None = None

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            try:
                re_rec = asyncio.run(
                    runner.run(
                        loaded_scenario,
                        provider=provider,
                        output_dir=tmp_path,
                        driver=agent_policy,
                    )
                )
                tmp_store = FileRecordingStore(tmp_path)
                re_journal = tmp_store.read_recording(str(re_rec.run_id))
            except Exception as exc:
                divergences.append(
                    SemanticDivergenceRecord(
                        sequence=len(divergences) + 1,
                        kind=SemanticDivergenceType.EVENT_TYPE_MISMATCH,
                        detail=f"Deterministic re-execution failed: {exc}",
                    )
                )
                legacy_divergences = tuple(d.to_legacy_divergence() for d in divergences)
                return ReplayReport(
                    recording_run_id=stem,
                    mode="verification",
                    integrity_status=integrity_status,
                    behaviour_status=BehaviourVerificationStatus.REEXECUTION_ERROR,
                    original_journal_digest=final_digest,
                    original_semantic_digest=orig_semantic_digest,
                    provenance_status=provenance_status,
                    divergences=legacy_divergences,
                    final_digest=final_digest,
                    entry_count=entry_count,
                )

        if re_journal is None:
            legacy_divergences = tuple(d.to_legacy_divergence() for d in divergences)
            return ReplayReport(
                recording_run_id=stem,
                mode="verification",
                integrity_status=integrity_status,
                behaviour_status=BehaviourVerificationStatus.REEXECUTION_ERROR,
                original_journal_digest=final_digest,
                original_semantic_digest=orig_semantic_digest,
                provenance_status=provenance_status,
                divergences=legacy_divergences,
                final_digest=final_digest,
                entry_count=entry_count,
            )

        # 6. Project replayed semantic events & compare
        re_semantic_events = tuple(project_semantic_event(e) for e in re_journal.entries)
        re_semantic_digest = compute_semantic_recording_digest(re_semantic_events)
        re_calls = len([e for e in re_journal.entries if e.type == "tool_call"])

        comparator = SemanticReplayComparator()
        comparison = comparator.compare(orig_semantic_events, re_semantic_events)

        if not comparison.verified:
            divergences.extend(comparison.divergences)
            behaviour_status = BehaviourVerificationStatus.DIVERGED
        else:
            behaviour_status = BehaviourVerificationStatus.VERIFIED

        legacy_divergences = tuple(d.to_legacy_divergence() for d in divergences)

        return ReplayReport(
            recording_run_id=stem,
            mode="verification",
            integrity_status=integrity_status,
            behaviour_status=behaviour_status,
            original_journal_digest=final_digest,
            replay_journal_digest=re_journal.final_digest(),
            original_semantic_digest=orig_semantic_digest,
            replay_semantic_digest=re_semantic_digest,
            provenance_status=provenance_status,
            divergences=legacy_divergences,
            final_digest=final_digest,
            entry_count=entry_count,
            re_executed_entry_count=re_journal.entry_count,
            re_executed_calls=re_calls,
        )

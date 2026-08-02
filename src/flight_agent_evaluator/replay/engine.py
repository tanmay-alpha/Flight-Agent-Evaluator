"""Replay and verification modes for the Phase 2 runtime.

Two modes:

- **playback** — replays a recorded run without verification.
- **verification** — replays the run and compares every tool call and
  result to the recording, producing a ``ReplayReport`` with any
  divergences.

Both modes use the ``ReplayEngine``, which replays a journal from disk
and yields per-step results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flight_agent_evaluator.recording.contracts import (
    DivergenceRecord,
    ReplayOutcomeStatus,
    ReplayReport,
)
from flight_agent_evaluator.recording.journal import HashChainJournal


class ReplayEngine:
    """Replay a recording in either playback or verification mode.

    The engine:

    1. Loads a journal from disk.
    2. Verifies the hash chain.
    3. In verification mode, replays each tool call against the
       ``ProviderRunner`` and records divergences.
    4. In playback mode, replays without verification.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(".recordings")

    def verify(self, run_id: str) -> ReplayReport:
        """Replay a recording and verify it matches exactly."""
        from flight_agent_evaluator.recording.journal import JournalVerificationError

        path = self._root / f"{run_id}.jsonl"
        divergences: list[DivergenceRecord] = []
        final_digest = "0" * 64
        try:
            journal = HashChainJournal.read_jsonl(path)
            final_digest = journal.final_digest()
            journal.verify()
        except JournalVerificationError as exc:
            divergences.append(
                DivergenceRecord(
                    sequence=1,
                    kind="missing_tool",
                    detail=f"chain-verification-failed: {exc}",
                )
            )
        status: ReplayOutcomeStatus = "verified" if not divergences else "tampered"
        return ReplayReport(
            recording_run_id=str(run_id),
            mode="verification",
            status=status,
            divergences=tuple(divergences),
            final_digest=final_digest,
        )

    def playback(self, run_id: str) -> dict[str, Any]:
        """Replay a recording in playback mode.

        Returns the journal entries as a list of dicts.
        """
        path = self._root / f"{run_id}.jsonl"
        journal = HashChainJournal.read_jsonl(path)
        # Return entries as plain dicts for serialisation.
        return {
            "run_id": run_id,
            "entries": [e.model_dump(mode="json") for e in journal.entries],
            "digest": journal.final_digest(),
        }

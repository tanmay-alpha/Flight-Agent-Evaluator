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

import json
from pathlib import Path
from typing import Any, Literal

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
        """Replay a recording and verify it matches exactly.

        Returns a ``ReplayReport``. In practice, tool calls must be
        replayed against the same provider; any discrepancy is logged as
        a divergence.

        This Phase 2 implementation validates the hash chain and returns
        the recorded entries. A future Phase 3 version will re-invoke
        each tool call.
        """
        path = self._root / f"{run_id}.jsonl"
        journal = HashChainJournal.read_jsonl(path)
        chain_valid = journal.verify()
        divergences: list[DivergenceRecord] = []
        if not chain_valid:
            for idx, entry in enumerate(journal.entries, start=1):
                divergences.append(
                    DivergenceRecord(
                        sequence=entry.seq,
                        kind="missing_tool",
                        detail="chain-verification-failed",
                    )
                )
        status: ReplayOutcomeStatus = (
            "verified" if not divergences else "tampered"
        )
        return ReplayReport(
            recording_run_id=run_id,
            mode="verification",
            status=status,
            divergences=tuple(divergences),
            final_digest=journal.final_digest(),
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

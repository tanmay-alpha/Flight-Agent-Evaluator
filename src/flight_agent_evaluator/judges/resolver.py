"""Evidence resolver mapping TrustedObservation IDs to exact journal sequences and tool calls."""

from __future__ import annotations

from typing import Any

from flight_agent_evaluator.judges.contracts import TrustedObservation
from flight_agent_evaluator.recording.contracts import JournalEntry
from flight_agent_evaluator.recording.journal import HashChainJournal


class EvidenceResolutionError(Exception):
    """Raised when an evidence ID cannot be resolved to recorded journal entries."""


class VerifiedEvidenceResolver:
    """Resolves TrustedObservation evidence IDs to exact recorded journal sequences."""

    def __init__(self, journal: HashChainJournal) -> None:
        self._journal = journal
        self._seq_index: dict[int, JournalEntry] = {e.seq: e for e in journal.entries}
        self._call_id_index: dict[str, JournalEntry] = {}

        for e in journal.entries:
            if e.type == "tool_call" and isinstance(e.payload, dict) and "call_id" in e.payload:
                self._call_id_index[str(e.payload["call_id"])] = e

    def resolve_observation(self, observation: TrustedObservation) -> dict[str, Any]:
        """Resolve a TrustedObservation to its underlying journal entry and context."""
        eid = observation.evidence_id
        src = observation.source

        # Parse potential seq references: "seq:5" or "tool_call:call-123"
        resolved_entry: JournalEntry | None = None

        if src.startswith("seq:"):
            try:
                seq_num = int(src.split(":", 1)[1])
                resolved_entry = self._seq_index.get(seq_num)
            except ValueError:
                pass
        elif src.startswith(("tool_call:", "call:")):
            call_id = src.split(":", 1)[1]
            resolved_entry = self._call_id_index.get(call_id)

        return {
            "evidence_id": eid,
            "source": src,
            "description": observation.description,
            "value": observation.value,
            "resolved_entry_seq": resolved_entry.seq if resolved_entry else None,
            "resolved_entry_type": resolved_entry.type if resolved_entry else None,
        }

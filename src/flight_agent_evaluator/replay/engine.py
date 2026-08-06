"""Replay and verification modes for the evaluation runtime.

Two modes:
- **playback** — replays a recorded run without verification.
- **verification** — replays the run, re-executes the scenario deterministically in-memory
  when scenario definition is resolved, and compares entries to locate behavioural divergences.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from flight_agent_evaluator.recording.contracts import (
    DivergenceRecord,
    ReplayOutcomeStatus,
    ReplayReport,
)
from flight_agent_evaluator.recording.journal import HashChainJournal, JournalVerificationError
from flight_agent_evaluator.recording.store import FileRecordingStore

logger = logging.getLogger(__name__)


class ReplayEngine:
    """Replay a recording in either playback or verification mode."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(".recordings")

    def verify(
        self,
        run_id: str,
        scenario_path: Path | None = None,
        provider: Any = None,
    ) -> ReplayReport:
        """Re-execute and verify a recorded run matching exact behaviour."""
        store = FileRecordingStore(self._root)

        try:
            recording = store.read_recording_summary(run_id)
            journal = store.read_recording(run_id)
        except Exception:
            # Fallback if metadata is missing but jsonl exists directly
            path = self._root / f"{run_id}.jsonl"
            if not path.is_file():
                return ReplayReport(
                    recording_run_id=str(run_id),
                    mode="verification",
                    status="replay_unavailable",
                    divergences=(
                        DivergenceRecord(
                            sequence=1,
                            kind="missing_tool",
                            detail="Recording or journal not found in store",
                        ),
                    ),
                    final_digest="0" * 64,
                )
            try:
                journal = HashChainJournal.read_jsonl(path)
                recording = None
            except Exception:
                return ReplayReport(
                    recording_run_id=str(run_id),
                    mode="verification",
                    status="replay_unavailable",
                    divergences=(
                        DivergenceRecord(
                            sequence=1,
                            kind="missing_tool",
                            detail="Journal unreadable",
                        ),
                    ),
                    final_digest="0" * 64,
                )

        divergences: list[DivergenceRecord] = []
        final_digest = journal.final_digest()
        journal_tampered = False

        try:
            journal.verify()
        except JournalVerificationError as exc:
            journal_tampered = True
            divergences.append(
                DivergenceRecord(
                    sequence=1,
                    kind="missing_tool",
                    detail=f"chain-verification-failed: {exc}",
                )
            )

        if journal_tampered:
            return ReplayReport(
                recording_run_id=str(run_id),
                mode="verification",
                status="recording_tampered",
                divergences=tuple(divergences),
                final_digest=final_digest,
                entry_count=len(journal.entries),
            )

        # Resolve scenario for full behavioural re-execution
        scenario_id = recording.scenario_id if recording else None
        from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

        loader = ScenarioLoader()
        loaded = None

        if scenario_path and scenario_path.exists():
            try:
                loaded = loader.load_from_path(scenario_path)
            except Exception:
                loaded = None

        if loaded is None and scenario_id:
            candidates = [
                Path(f"resources/scenarios/{scenario_id}.json"),
                Path(f"tests/fixtures/scenarios/{scenario_id}.json"),
                Path("resources/scenarios/smoke_phase2.json"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    try:
                        candidate_loaded = loader.load_from_path(candidate)
                        if candidate_loaded.scenario.scenario_id.id == scenario_id:
                            loaded = candidate_loaded
                            break
                    except Exception as exc:
                        logger.debug("Candidate scenario %s failed to load: %s", candidate, exc)
                        continue

        if loaded is None:
            # Integrity is valid, but full scenario re-execution is unavailable
            return ReplayReport(
                recording_run_id=str(run_id),
                mode="verification",
                status="integrity_valid",
                divergences=(),
                final_digest=final_digest,
                entry_count=len(journal.entries),
            )

        # Re-execute scenario in isolated temporary directory
        from flight_agent_evaluator.engine.runner import ScenarioRunner

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            runner = ScenarioRunner()
            try:
                re_executed_rec = asyncio.run(
                    runner.run(loaded, provider=provider, output_dir=tmp_path)
                )
                tmp_store = FileRecordingStore(tmp_path)
                re_journal = tmp_store.read_recording(str(re_executed_rec.run_id))
            except Exception as exc:
                divergences.append(
                    DivergenceRecord(
                        sequence=len(divergences) + 1,
                        kind="missing_tool",
                        detail=f"Re-execution failed: {exc}",
                    )
                )
                return ReplayReport(
                    recording_run_id=str(run_id),
                    mode="verification",
                    status="behaviour_diverged",
                    divergences=tuple(divergences),
                    final_digest=final_digest,
                    entry_count=len(journal.entries),
                )

        # Compare entries
        orig_tool_entries = [e for e in journal.entries if e.type in ("tool_call", "tool_result")]
        re_tool_entries = [e for e in re_journal.entries if e.type in ("tool_call", "tool_result")]
        re_calls = len([e for e in re_tool_entries if e.type == "tool_call"])

        seq = len(divergences) + 1
        if len(orig_tool_entries) != len(re_tool_entries):
            divergences.append(
                DivergenceRecord(
                    sequence=seq,
                    kind="missing_tool"
                    if len(orig_tool_entries) > len(re_tool_entries)
                    else "extra_tool",
                    detail=f"Tool entry count mismatch: original={len(orig_tool_entries)}, re-executed={len(re_tool_entries)}",
                )
            )

        min_len = min(len(orig_tool_entries), len(re_tool_entries))
        for idx in range(min_len):
            orig_e = orig_tool_entries[idx]
            re_e = re_tool_entries[idx]
            if orig_e.type != re_e.type:
                divergences.append(
                    DivergenceRecord(
                        sequence=seq + idx,
                        kind="tool_status_mismatch",
                        detail=f"Entry type mismatch at index {idx}: {orig_e.type} != {re_e.type}",
                    )
                )
            elif orig_e.type == "tool_call":
                o_tool = orig_e.payload.get("tool_name")
                r_tool = re_e.payload.get("tool_name")
                if o_tool != r_tool:
                    divergences.append(
                        DivergenceRecord(
                            sequence=seq + idx,
                            kind="tool_status_mismatch",
                            detail=f"Tool name mismatch at call {idx}: {o_tool} != {r_tool}",
                        )
                    )
            elif orig_e.type == "tool_result":
                o_stat = orig_e.payload.get("status")
                r_stat = re_e.payload.get("status")
                if o_stat != r_stat:
                    divergences.append(
                        DivergenceRecord(
                            sequence=seq + idx,
                            kind="tool_status_mismatch",
                            detail=f"Tool status mismatch at call {idx}: {o_stat} != {r_stat}",
                        )
                    )

        final_status: ReplayOutcomeStatus = (
            "behaviour_diverged" if divergences else "behaviour_verified"
        )

        return ReplayReport(
            recording_run_id=str(run_id),
            mode="verification",
            status=final_status,
            divergences=tuple(divergences),
            final_digest=final_digest,
            entry_count=len(journal.entries),
            re_executed_calls=re_calls,
        )

    def playback(self, run_id: str) -> dict[str, Any]:
        """Replay a recording in playback mode.

        Returns the journal entries as a list of dicts.
        """
        path = self._root / f"{run_id}.jsonl"
        journal = HashChainJournal.read_jsonl(path)
        return {
            "run_id": run_id,
            "entries": [e.model_dump(mode="json") for e in journal.entries],
            "digest": journal.final_digest(),
        }

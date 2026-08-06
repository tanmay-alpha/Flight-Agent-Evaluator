"""Branch coverage tests for ReplayEngine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from flight_agent_evaluator.recording.contracts import JournalEntry, RunRecording
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.replay.engine import ReplayEngine


def test_replay_verify_missing_file_returns_unavailable(tmp_path: Path):
    engine = ReplayEngine(tmp_path)
    report = engine.verify("nonexistent-run-id")
    assert report.status == "replay_unavailable"
    assert report.final_digest == "0" * 64


def test_replay_verify_corrupted_journal_unreadable(tmp_path: Path):
    run_id = str(uuid.uuid4())
    jsonl_path = tmp_path / f"{run_id}.jsonl"
    jsonl_path.write_text("invalid json content\n", encoding="utf-8")

    engine = ReplayEngine(tmp_path)
    report = engine.verify(run_id)
    assert report.status == "replay_unavailable"
    assert "unreadable" in report.divergences[0].detail.lower()


def test_replay_verify_valid_integrity_unresolved_scenario(tmp_path: Path):
    store = FileRecordingStore(tmp_path)
    run_id = str(uuid.uuid4())

    journal = HashChainJournal()
    journal.append(
        JournalEntry(
            v=1,
            seq=1,
            id=uuid.uuid4(),
            type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={"scenario_id": "unresolved_sc"},
            prev_hash="",
            hash="",
        )
    )
    rec = RunRecording(
        run_id=uuid.UUID(run_id),
        scenario_id="unresolved_sc",
        scenario_version=1,
        seed=42,
        entry_count=1,
        final_digest=journal.final_digest(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    store.write_recording(run_id, journal, rec)

    engine = ReplayEngine(tmp_path)
    report = engine.verify(run_id)
    assert report.status == "integrity_valid"
    assert len(report.divergences) == 0


def test_replay_verify_behaviour_verified_with_real_scenario(tmp_path: Path):
    scenario_path = Path("resources/scenarios/jfk-lhr-delay.json")

    from flight_agent_evaluator.engine.runner import ScenarioRunner
    from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

    loader = ScenarioLoader()
    loaded = loader.load_from_path(scenario_path)

    import asyncio

    runner = ScenarioRunner()
    rec = asyncio.run(runner.run(loaded, output_dir=tmp_path))

    engine = ReplayEngine(tmp_path)
    report = engine.verify(str(rec.run_id), scenario_path=scenario_path)
    assert report.status == "behaviour_verified"
    assert report.re_executed_calls > 0


def test_replay_verify_behaviour_diverged_tool_mismatch(tmp_path: Path):
    scenario_path = Path("resources/scenarios/jfk-lhr-delay.json")

    from flight_agent_evaluator.engine.runner import ScenarioRunner
    from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

    loader = ScenarioLoader()
    loaded = loader.load_from_path(scenario_path)

    import asyncio

    runner = ScenarioRunner()
    rec = asyncio.run(runner.run(loaded, output_dir=tmp_path))

    # Tamper with tool call in journal (without breaking hash chain if we append extra entry)
    store = FileRecordingStore(tmp_path)
    journal = store.read_recording(str(rec.run_id))

    journal.append_event(
        "tool_call",
        run_id=str(rec.run_id),
        correlation_id="tamper",
        time=datetime.now(UTC).isoformat(),
        payload={"tool_name": "extra.tool", "call_id": "extra-1"},
    )
    store.write_recording(str(rec.run_id), journal, rec)

    engine = ReplayEngine(tmp_path)
    report = engine.verify(str(rec.run_id), scenario_path=scenario_path)
    assert report.status == "behaviour_diverged"
    assert len(report.divergences) > 0

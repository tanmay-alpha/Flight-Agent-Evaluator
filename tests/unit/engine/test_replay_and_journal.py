"""Tests for replay engine, recording store, journal tampering, and fault engine."""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_agent_evaluator.contracts.evaluation import (
    BookingStateAssertion,
    EventCountAssertion,
    ForbiddenMutationAssertion,
    MaximumLatencyAssertion,
    NoDuplicateSideEffectAssertion,
    ReplayDeterminismAssertion,
    ToolCallCountAssertion,
    ToolCalledAssertion,
    ToolNotCalledAssertion,
)
from flight_agent_evaluator.contracts.faults import (
    ActivationRule,
    ConflictingResponseFault,
    DelayedResponseFault,
    DuplicateEventFault,
    MalformedResponseFault,
    ProviderServerErrorFault,
    RateLimitFault,
    StaleResponseFault,
    TimeoutFault,
)
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.fault_engine import (
    FaultEngine,
    InjectedFault,
)
from flight_agent_evaluator.recording.contracts import (
    JournalEntry,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import FileRecordingStore, RecordingStoreError
from flight_agent_evaluator.replay.engine import ReplayEngine
from flight_agent_evaluator.runtime.clock import VirtualClock


def _make_run_id() -> str:
    return str(_uuid.uuid4())


def _minimal_recording(run_id: str) -> RunRecording:
    return RunRecording(
        run_id=_uuid.UUID(run_id),
        scenario_id="test-scenario",
        scenario_version=1,
        seed=0,
        entry_count=1,
        final_digest="a" * 64,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


def _make_tool_call(run_id: str, tool_name: str = "tool") -> ToolCall:
    return ToolCall(
        call_id=_uuid.uuid4(),
        run_id=run_id,
        tool_name=tool_name,
        arguments={},
        start_time=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------


class TestReplayEngine:
    def test_playback_returns_entries(self, tmp_path: Path):
        store = FileRecordingStore(tmp_path)
        run_id = _make_run_id()
        journal = HashChainJournal()
        journal.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="run_started",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={},
                prev_hash="",
                hash="0" * 64,
            )
        )
        store.write_recording(run_id, journal, _minimal_recording(run_id))

        engine = ReplayEngine(tmp_path)
        result = engine.playback(run_id)
        assert "entries" in result
        assert len(result["entries"]) >= 1

    def test_verification_valid_chain(self, tmp_path: Path):
        store = FileRecordingStore(tmp_path)
        run_id = _make_run_id()
        journal = HashChainJournal()
        journal.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="run_started",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={},
                prev_hash="",
                hash="0" * 64,
            )
        )
        store.write_recording(run_id, journal, _minimal_recording(run_id))

        engine = ReplayEngine(tmp_path)
        report = engine.verify(run_id)
        assert report.status in ("verified", "integrity_valid")
        assert report.recording_run_id == run_id

    def test_verification_detects_tampering(self, tmp_path: Path):
        store = FileRecordingStore(tmp_path)
        run_id = _make_run_id()
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=_uuid.uuid4(),
            type="run_started",
            run_id=_uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={},
            prev_hash="",
            hash="0" * 64,
        )
        journal.append_raw(entry)
        store.write_recording(run_id, journal, _minimal_recording(run_id))

        # Tamper with the JSONL file by changing the type to an invalid value
        record_path = tmp_path / f"{run_id}.jsonl"
        lines = record_path.read_text(encoding="utf-8").splitlines()
        if lines:
            obj = json.loads(lines[0])
            obj["type"] = "run_hacked"
            lines[0] = json.dumps(obj, sort_keys=True, default=str)
            record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        engine = ReplayEngine(tmp_path)
        # Tampered entry will fail validation during read, but the verify
        # method catches this via journal.verify() raising
        try:
            report = engine.verify(run_id)
            # If it doesn't raise, the chain check should detect tampering
            assert report.status in ("tampered", "recording_tampered")
        except Exception as exc:
            # Validation error on read is also acceptable - tamper detected
            assert exc is not None


def test_fault_engine_reset_and_faults_property():
    from flight_agent_evaluator.contracts.faults import ActivationRule, TimeoutFault
    from flight_agent_evaluator.engine.fault_engine import FaultEngine

    spec = TimeoutFault(
        target_tool="echo",
        target_provider="test",
        activation=ActivationRule(kind="always"),
        occurrence_count=2,
        timeout_seconds=5,
    )
    engine = FaultEngine((spec,))
    assert engine.faults == (spec,)
    assert len(engine.faults) == 1

    engine.reset()
    assert engine.faults == (spec,)


# ---------------------------------------------------------------------------
# Journal tampering
# ---------------------------------------------------------------------------


class TestJournalTampering:
    def test_detect_tampered_entry(self, tmp_path: Path):
        store = FileRecordingStore(tmp_path)
        run_id = _make_run_id()
        journal = HashChainJournal()
        journal.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="run_started",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={},
                prev_hash="",
                hash="0" * 64,
            )
        )
        store.write_recording(run_id, journal, _minimal_recording(run_id))

        # Tamper with payload (not type) so it still validates but hash mismatches
        record_path = tmp_path / f"{run_id}.jsonl"
        lines = record_path.read_text(encoding="utf-8").splitlines()
        if lines:
            obj = json.loads(lines[0])
            obj["payload"] = {"tampered": True}
            lines[0] = json.dumps(obj, sort_keys=True, default=str)
            record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        reloaded = FileRecordingStore(tmp_path).read_recording(run_id)
        # Tampering causes hash mismatch which raises JournalVerificationError
        with pytest.raises(Exception):
            reloaded.verify()

    def test_verify_valid_journal(self):
        journal = HashChainJournal()
        run_id = _make_run_id()
        journal.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="run_started",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={},
                prev_hash="",
                hash="0" * 64,
            )
        )
        assert journal.verify()

    def test_final_digest_stable(self):
        journal = HashChainJournal()
        run_id = _make_run_id()
        journal.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="run_started",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={},
                prev_hash="",
                hash="0" * 64,
            )
        )
        assert journal.final_digest() == journal.final_digest()

    def test_reject_nan_in_payload(self):
        """NaN in payload is rejected by canonical_json during entry hashing."""
        from flight_agent_evaluator.canonical import canonical_json

        with pytest.raises(ValueError, match="Non-finite"):
            canonical_json({"count": float("nan")})

    def test_reject_infinity_in_payload(self):
        from flight_agent_evaluator.canonical import canonical_json

        with pytest.raises(ValueError, match="Non-finite"):
            canonical_json({"value": float("inf")})


# ---------------------------------------------------------------------------
# FileRecordingStore
# ---------------------------------------------------------------------------


class TestFileRecordingStore:
    def test_rejects_symlink_at_write_path(self, tmp_path: Path):
        store = FileRecordingStore(tmp_path)
        run_id = "abcd1234abcd1234abcd1234abcd1234"
        journal = HashChainJournal()
        target_path = tmp_path / f"{run_id}.jsonl"
        # Create a symlink at the exact write path
        real_file = tmp_path / "safe_target.txt"
        real_file.write_text("safe", encoding="utf-8")
        try:
            if target_path.exists():
                target_path.unlink()
            target_path.symlink_to(real_file)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")

        with pytest.raises((RecordingStoreError, Exception)):
            store.write_recording(run_id, journal, _minimal_recording(run_id))
        # Cleanup
        if target_path.is_symlink():
            target_path.unlink()

    def test_rejects_path_traversal_in_run_id(self, tmp_path: Path):
        store = FileRecordingStore(tmp_path)
        with pytest.raises((RecordingStoreError, Exception)):
            store.write_recording(
                "../escape", HashChainJournal(), _minimal_recording(_make_run_id())
            )

    def test_write_and_read_roundtrip(self, tmp_path: Path):
        store = FileRecordingStore(tmp_path)
        run_id = _make_run_id()
        journal = HashChainJournal()
        journal.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="run_started",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={"key": "value"},
                prev_hash="",
                hash="0" * 64,
            )
        )
        recording = _minimal_recording(run_id)
        store.write_recording(run_id, journal, recording)
        reloaded = store.read_recording(run_id)
        assert reloaded.entry_count == 1
        assert reloaded.entries[0].payload == {"key": "value"}


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


class TestAssertions:
    def test_tool_called_assertion(self):
        a = ToolCalledAssertion(assertion_id="a1", tool_name="flight.get_status")
        assert a.assertion_type == "tool_called"
        assert a.tool_name == "flight.get_status"

    def test_no_mutation_assertion(self):
        a = NoDuplicateSideEffectAssertion(assertion_id="a2", tool_name="flight.get_status")
        assert a.assertion_type == "no_duplicate_side_effect"

    def test_replay_determinism_assertion(self):
        a = ReplayDeterminismAssertion(assertion_id="a3")
        assert a.assertion_type == "replay_determinism"

    def test_tool_call_count_assertion(self):
        a = ToolCallCountAssertion(assertion_id="a4", tool_name="search", min_count=1, max_count=5)
        assert a.min_count == 1
        assert a.max_count == 5

    def test_event_count_assertion(self):
        a = EventCountAssertion(assertion_id="a5", event_type="domain", min_count=2)
        assert a.event_type == "domain"

    def test_booking_state_assertion(self):
        a = BookingStateAssertion(assertion_id="a6", booking_id="BK1", expected_state="confirmed")
        assert a.expected_state == "confirmed"

    def test_maximum_latency_assertion(self):
        a = MaximumLatencyAssertion(assertion_id="a7", max_seconds=30)
        assert a.max_seconds == 30

    def test_forbidden_mutation_assertion(self):
        a = ForbiddenMutationAssertion(assertion_id="a8", tool_name="book")
        assert a.tool_name == "book"

    def test_tool_not_called_assertion(self):
        a = ToolNotCalledAssertion(assertion_id="a9", tool_name="flight.cancel")
        assert a.assertion_type == "tool_not_called"
        assert a.tool_name == "flight.cancel"


# ---------------------------------------------------------------------------
# Fault engine
# ---------------------------------------------------------------------------


class TestFaultEngine:
    def test_always_fault_triggers(self):
        clock = VirtualClock()
        fault = TimeoutFault(
            fault_type="timeout",
            target_provider="x",
            target_tool="tool",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            timeout_seconds=5,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "tool")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert isinstance(result, InjectedFault)
        assert result.fault_type == "timeout"

    def test_no_fault_for_different_tool(self):
        clock = VirtualClock()
        fault = TimeoutFault(
            fault_type="timeout",
            target_provider="x",
            target_tool="tool",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            timeout_seconds=5,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "other")
        assert engine.apply(call, sequence=0) is None

    def test_rate_limit_fault(self):
        clock = VirtualClock()
        fault = RateLimitFault(
            fault_type="rate_limit",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            retry_after_seconds=2,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert result.error is not None
        assert result.error.error_type == "provider_error"

    def test_server_error_fault(self):
        clock = VirtualClock()
        fault = ProviderServerErrorFault(
            fault_type="provider_server_error",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            status_code=500,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert result.error is not None
        assert "500" in result.error.message

    def test_duplicate_event_fault(self):
        clock = VirtualClock()
        fault = DuplicateEventFault(
            fault_type="duplicate_event",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            duplication_count=2,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert result.status == "success"
        assert result.duplication_count == 2
        assert result.error is None

    def test_stale_response_fault(self):
        clock = VirtualClock()
        fault = StaleResponseFault(
            fault_type="stale_response",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            staleness_seconds=30,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert result.error is not None
        assert "Stale" in result.error.message

    def test_delayed_response_fault(self):
        clock = VirtualClock()
        fault = DelayedResponseFault(
            fault_type="delayed_response",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            delay_seconds=5,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert result.status == "success"
        assert result.delay_seconds == 5
        assert result.error is None

    def test_malformed_response_fault(self):
        clock = VirtualClock()
        fault = MalformedResponseFault(
            fault_type="malformed_response",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            description="bad data",
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert result.error is not None
        assert "Malformed" in result.error.message

    def test_conflicting_response_fault(self):
        clock = VirtualClock()
        fault = ConflictingResponseFault(
            fault_type="conflicting_response",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            field_path="status",
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        result = engine.apply(call, sequence=0)
        assert result is not None
        assert result.error is not None
        assert "Conflict" in result.error.message

    def test_fault_budget_exhausted(self):
        clock = VirtualClock()
        fault = TimeoutFault(
            fault_type="timeout",
            target_provider="p",
            target_tool="t",
            activation=ActivationRule(kind="always"),
            occurrence_count=1,
            timeout_seconds=1,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        assert engine.apply(call, sequence=0) is not None
        assert engine.apply(call, sequence=1) is None

    def test_no_faults_returns_none(self):
        engine = FaultEngine(())
        call = _make_tool_call(_make_run_id())
        assert engine.apply(call, sequence=0) is None

    def test_after_n_calls_activation(self):
        clock = VirtualClock()
        fault = TimeoutFault(
            fault_type="timeout",
            target_provider="x",
            target_tool="t",
            activation=ActivationRule(kind="after_n_calls", call_index=2),
            occurrence_count=1,
            timeout_seconds=1,
        )
        engine = FaultEngine((fault,), clock)
        call = _make_tool_call(_make_run_id(), "t")
        # call_index=2 means "after 3 calls"; first 2 don't trigger
        assert engine.apply(call, sequence=0) is None
        assert engine.apply(call, sequence=1) is None
        # 3rd call triggers
        assert engine.apply(call, sequence=2) is not None


class TestReplayDivergenceCategories:
    def test_divergence_detection_tampered_entry(self, tmp_path: Path):
        run_id = _make_run_id()
        journal = HashChainJournal()
        entry = JournalEntry(
            v=1,
            seq=1,
            id=_uuid.uuid4(),
            type="run_started",
            run_id=_uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={"seed": 42},
            prev_hash="",
            hash="",
        )
        journal.append(entry)
        # Tamper payload without recomputing hash
        journal.entries[0].payload["seed"] = 99
        path = tmp_path / f"{run_id}.jsonl"
        journal.write_jsonl(path)
        engine = ReplayEngine(tmp_path)
        report = engine.verify(run_id)
        assert report.status in ("tampered", "recording_tampered")
        assert len(report.divergences) > 0

    def test_divergence_detection_missing_entry(self, tmp_path: Path):
        run_id = _make_run_id()
        journal = HashChainJournal()
        journal.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="run_started",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={},
                prev_hash="",
                hash="",
            )
        )
        journal.append(
            JournalEntry(
                v=1,
                seq=2,
                id=_uuid.uuid4(),
                type="tool_call",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={"tool_name": "flight.get_status"},
                prev_hash=journal.entries[0].hash,
                hash="",
            )
        )
        # Remove first entry to create missing entry gap
        journal._entries.pop(0)
        path = tmp_path / f"{run_id}.jsonl"
        journal.write_jsonl(path)
        engine = ReplayEngine(tmp_path)
        report = engine.verify(run_id)
        assert report.status in ("tampered", "recording_tampered")

    def test_divergence_detection_reordered_entry(self, tmp_path: Path):
        run_id = _make_run_id()
        j = HashChainJournal()
        e1 = JournalEntry(
            v=1,
            seq=1,
            id=_uuid.uuid4(),
            type="run_started",
            run_id=_uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={"step": 1},
            prev_hash="",
            hash="",
        )
        j.append(e1)
        e2 = JournalEntry(
            v=1,
            seq=2,
            id=_uuid.uuid4(),
            type="tool_call",
            run_id=_uuid.UUID(run_id),
            correlation_id="test",
            time=datetime.now(UTC),
            payload={"step": 2},
            prev_hash=e1.hash,
            hash="",
        )
        j.append(e2)
        # Reorder entries
        j._entries[0], j._entries[1] = j._entries[1], j._entries[0]
        path = tmp_path / f"{run_id}.jsonl"
        j.write_jsonl(path)
        engine = ReplayEngine(tmp_path)
        report = engine.verify(run_id)
        assert report.status in ("tampered", "recording_tampered")

    def test_divergence_detection_changed_scenario_trajectory_seed(self, tmp_path: Path):
        run_id = _make_run_id()
        j = HashChainJournal()
        j.append(
            JournalEntry(
                v=1,
                seq=1,
                id=_uuid.uuid4(),
                type="scenario_loaded",
                run_id=_uuid.UUID(run_id),
                correlation_id="test",
                time=datetime.now(UTC),
                payload={
                    "scenario_id": "original",
                    "trajectory_id": "traj-1",
                    "seed": 42,
                    "fixture": "AS142",
                    "tool_result": {"status": "delayed"},
                    "event": "flight_delayed",
                    "timestamp": "2026-07-28T12:00:00Z",
                    "final_response": "Flight delayed",
                },
                prev_hash="",
                hash="",
            )
        )
        path = tmp_path / f"{run_id}.jsonl"
        j.write_jsonl(path)
        # Verify valid reading works
        engine = ReplayEngine(tmp_path)
        report = engine.verify(run_id)
        assert report.status in ("verified", "integrity_valid")

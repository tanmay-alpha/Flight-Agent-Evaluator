"""Red-team reproduction tests for Layer 4 Replay and Evidence Integrity.

Tests L4-R01 through L4-R10 reproduce vulnerabilities and defects present in
the baseline recording/replay and evidence infrastructure.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_agent_evaluator.agent.model_client import ReplayModelClient
from flight_agent_evaluator.contracts.model import (
    ModelExchange,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
)
from flight_agent_evaluator.judges.contracts import (
    JudgeEvidencePackage,
    TrustedObservation,
)
from flight_agent_evaluator.recording.contracts import (
    JournalEntry,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import (
    HashChainJournal,
    JournalVerificationError,
)
from flight_agent_evaluator.recording.store import (
    FileRecordingStore,
)
from flight_agent_evaluator.replay.engine import ReplayEngine


def _create_sample_journal(run_id: str, scenario_id: str = "jfk-lhr-delay") -> HashChainJournal:
    """Helper to create a simple valid HashChainJournal."""
    j = HashChainJournal()
    j.append_event(
        entry_type="run_started",
        run_id=run_id,
        correlation_id=f"corr-{run_id}-0",
        time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        payload={"scenario_id": scenario_id, "seed": 42},
    )
    j.append_event(
        entry_type="tool_call",
        run_id=run_id,
        correlation_id=f"corr-{run_id}-1",
        time=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        payload={
            "tool_name": "flight.get_status",
            "arguments": {"flight_id": "AA100"},
            "call_id": "call-1",
        },
    )
    j.append_event(
        entry_type="tool_result",
        run_id=run_id,
        correlation_id=f"corr-{run_id}-2",
        time=datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
        payload={
            "status": "success",
            "value": {"status": "DELAYED", "delay_minutes": 180},
            "call_id": "call-1",
        },
    )
    j.append_event(
        entry_type="final_response",
        run_id=run_id,
        correlation_id=f"corr-{run_id}-3",
        time=datetime(2026, 1, 1, 12, 0, 3, tzinfo=UTC),
        payload={"response": "Flight AA100 is delayed by 180 minutes."},
    )
    j.append_event(
        entry_type="run_completed",
        run_id=run_id,
        correlation_id=f"corr-{run_id}-4",
        time=datetime(2026, 1, 1, 12, 0, 4, tzinfo=UTC),
        payload={"stop_reason": "completed"},
    )
    return j


def test_l4_r01_tool_result_semantic_payload_divergence() -> None:
    """L4-R01: Divergence in tool result payload/value must cause behaviour verification to fail."""
    from flight_agent_evaluator.replay.comparator import SemanticReplayComparator
    from flight_agent_evaluator.replay.projection import project_semantic_event

    run_id = str(uuid.uuid4())
    j_orig = _create_sample_journal(run_id)

    # Replay journal has status="success" but different value payload ("ON_TIME")
    j_replay = HashChainJournal()
    for e in j_orig.entries:
        if e.type == "tool_result":
            j_replay.append_event(
                entry_type="tool_result",
                run_id=run_id,
                correlation_id=e.correlation_id,
                time=e.time,
                payload={
                    "status": "success",
                    "value": {"status": "ON_TIME", "delay_minutes": 0},
                    "call_id": "call-1",
                },
            )
        else:
            j_replay.append_event(
                entry_type=e.type,
                run_id=run_id,
                correlation_id=e.correlation_id,
                time=e.time,
                payload=e.payload,
            )

    events_orig = tuple(project_semantic_event(e) for e in j_orig.entries)
    events_replay = tuple(project_semantic_event(e) for e in j_replay.entries)

    comparator = SemanticReplayComparator()
    comparison = comparator.compare(events_orig, events_replay)

    assert not comparison.verified
    assert any(
        "result" in d.kind.value.lower() or "value" in d.kind.value.lower()
        for d in comparison.divergences
    )


def test_l4_r02_tool_argument_divergence() -> None:
    """L4-R02: Divergence in tool arguments must cause behaviour verification to fail."""
    from flight_agent_evaluator.replay.comparator import SemanticReplayComparator
    from flight_agent_evaluator.replay.projection import project_semantic_event

    run_id = str(uuid.uuid4())
    j_orig = _create_sample_journal(run_id)

    # Replay journal called tool with different flight_id
    j_replay = HashChainJournal()
    for e in j_orig.entries:
        if e.type == "tool_call":
            j_replay.append_event(
                entry_type="tool_call",
                run_id=run_id,
                correlation_id=e.correlation_id,
                time=e.time,
                payload={
                    "tool_name": "flight.get_status",
                    "arguments": {"flight_id": "AA999"},
                    "call_id": "call-1",
                },
            )
        else:
            j_replay.append_event(
                entry_type=e.type,
                run_id=run_id,
                correlation_id=e.correlation_id,
                time=e.time,
                payload=e.payload,
            )

    events_orig = tuple(project_semantic_event(e) for e in j_orig.entries)
    events_replay = tuple(project_semantic_event(e) for e in j_replay.entries)

    comparator = SemanticReplayComparator()
    comparison = comparator.compare(events_orig, events_replay)

    assert not comparison.verified
    assert any("argument" in d.kind.value.lower() for d in comparison.divergences)


def test_l4_r03_final_response_divergence() -> None:
    """L4-R03: Divergence in final response must cause behaviour verification to fail."""
    from flight_agent_evaluator.replay.comparator import SemanticReplayComparator
    from flight_agent_evaluator.replay.projection import project_semantic_event

    run_id = str(uuid.uuid4())
    j_orig = _create_sample_journal(run_id)

    j_replay = HashChainJournal()
    for e in j_orig.entries:
        if e.type == "final_response":
            j_replay.append_event(
                entry_type="final_response",
                run_id=run_id,
                correlation_id=e.correlation_id,
                time=e.time,
                payload={"response": "Flight AA100 is completely on time."},
            )
        else:
            j_replay.append_event(
                entry_type=e.type,
                run_id=run_id,
                correlation_id=e.correlation_id,
                time=e.time,
                payload=e.payload,
            )

    events_orig = tuple(project_semantic_event(e) for e in j_orig.entries)
    events_replay = tuple(project_semantic_event(e) for e in j_replay.entries)

    comparator = SemanticReplayComparator()
    comparison = comparator.compare(events_orig, events_replay)

    assert not comparison.verified
    assert any("final_response" in d.kind.value.lower() for d in comparison.divergences)


def test_l4_r04_state_divergence() -> None:
    """L4-R04: Divergence in final state snapshot must cause behaviour verification to fail."""
    from flight_agent_evaluator.replay.comparator import SemanticReplayComparator
    from flight_agent_evaluator.replay.projection import project_semantic_event

    run_id = str(uuid.uuid4())
    j_orig = HashChainJournal()
    j_orig.append_event(
        "run_started", run_id, "c0", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC), {"seed": 1}
    )
    j_orig.append_event(
        "state_snapshot",
        run_id,
        "c1",
        datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        {"booking_status": "REBOOKED"},
    )
    j_orig.append_event(
        "run_completed",
        run_id,
        "c2",
        datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
        {"stop_reason": "done"},
    )

    j_replay = HashChainJournal()
    j_replay.append_event(
        "run_started", run_id, "c0", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC), {"seed": 1}
    )
    j_replay.append_event(
        "state_snapshot",
        run_id,
        "c1",
        datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        {"booking_status": "DISRUPTED"},
    )
    j_replay.append_event(
        "run_completed",
        run_id,
        "c2",
        datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
        {"stop_reason": "done"},
    )

    events_orig = tuple(project_semantic_event(e) for e in j_orig.entries)
    events_replay = tuple(project_semantic_event(e) for e in j_replay.entries)

    comparator = SemanticReplayComparator()
    comparison = comparator.compare(events_orig, events_replay)

    assert not comparison.verified
    assert any("state" in d.kind.value.lower() for d in comparison.divergences)


def test_l4_r05_fault_divergence() -> None:
    """L4-R05: Divergence in fault injection must cause behaviour verification to fail."""
    from flight_agent_evaluator.replay.comparator import SemanticReplayComparator
    from flight_agent_evaluator.replay.projection import project_semantic_event

    run_id = str(uuid.uuid4())
    j_orig = HashChainJournal()
    j_orig.append_event(
        "run_started", run_id, "c0", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC), {"seed": 1}
    )
    j_orig.append_event(
        "fault_injected",
        run_id,
        "c1",
        datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
        {"fault_type": "timeout", "target": "flight.get_status"},
    )
    j_orig.append_event(
        "run_completed",
        run_id,
        "c2",
        datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
        {"stop_reason": "done"},
    )

    j_replay = HashChainJournal()
    j_replay.append_event(
        "run_started", run_id, "c0", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC), {"seed": 1}
    )
    # No fault injected in replay
    j_replay.append_event(
        "run_completed",
        run_id,
        "c2",
        datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
        {"stop_reason": "done"},
    )

    events_orig = tuple(project_semantic_event(e) for e in j_orig.entries)
    events_replay = tuple(project_semantic_event(e) for e in j_replay.entries)

    comparator = SemanticReplayComparator()
    comparison = comparator.compare(events_orig, events_replay)

    assert not comparison.verified
    assert any(
        "fault" in d.kind.value.lower()
        or "missing" in d.kind.value.lower()
        or "mismatch" in d.kind.value.lower()
        for d in comparison.divergences
    )


@pytest.mark.anyio
async def test_l4_r06_model_response_tamper_rejected() -> None:
    """L4-R06: Modifying model response content while retaining old response_digest must fail closed."""
    from flight_agent_evaluator.agent.errors import ModelReplayResponseDigestMismatchError

    req = ModelRequest(
        messages=[{"role": "user", "content": "hello"}],
        model_id="gpt-4o-mini",
        turn_index=0,
        prompt_policy_id="default-policy",
        prompt_policy_version="1.0.0",
        prompt_digest="0" * 64,
    )
    req_fp = req.canonical_fingerprint()

    orig_resp = ModelResponse(
        content="Original answer",
        tool_calls=[],
        model_id="gpt-4o-mini",
        finish_reason="stop",
    )
    orig_resp_digest = orig_resp.canonical_digest()

    # Tampered response: different content, but old response_digest retained in exchange
    tampered_resp = ModelResponse(
        content="Tampered malicious answer",
        tool_calls=[],
        model_id="gpt-4o-mini",
        finish_reason="stop",
    )

    tampered_exchange = ModelExchange(
        exchange_id="ex-1",
        turn_index=0,
        request=req,
        request_fingerprint=req_fp,
        response=tampered_resp,
        response_digest=orig_resp_digest,  # STALE DIGEST
    )

    from flight_agent_evaluator.contracts.model import ModelConfiguration

    manifest = ModelExchangeManifest(
        manifest_id="manifest-1",
        model_configuration=ModelConfiguration(
            provider="openai",
            model_id="gpt-4o-mini",
        ),
        exchanges=[tampered_exchange],
    )

    client = ReplayModelClient(manifest)
    with pytest.raises((ModelReplayResponseDigestMismatchError, RuntimeError)) as excinfo:
        await client.create_completion(req)
    assert (
        "digest" in str(excinfo.value).lower()
        or "mismatch" in str(excinfo.value).lower()
        or "tamper" in str(excinfo.value).lower()
    )


def test_l4_r07_judge_evidence_collision() -> None:
    """L4-R07: Modifying trusted observations must change the JudgeEvidencePackage semantic digest."""
    obs_a = [
        TrustedObservation(
            evidence_id="ev-1",
            source="journal.tool_result",
            description="Flight AA100 is delayed 180 minutes.",
            value="delayed_180",
        )
    ]
    obs_b = [
        TrustedObservation(
            evidence_id="ev-1",
            source="journal.tool_result",
            description="Flight AA100 is on time.",
            value="on_time",
        )
    ]

    pkg_a = JudgeEvidencePackage(
        scenario_id="jfk-lhr-delay",
        run_id="run-123",
        public_task="Check flight status",
        trusted_observations=obs_a,
        final_response="Flight AA100 is delayed.",
        tool_call_summary="flight.get_status",
        created_at=datetime.now(UTC),
    )

    pkg_b = JudgeEvidencePackage(
        scenario_id="jfk-lhr-delay",
        run_id="run-123",
        public_task="Check flight status",
        trusted_observations=obs_b,
        final_response="Flight AA100 is delayed.",
        tool_call_summary="flight.get_status",
        created_at=datetime.now(UTC),
    )

    digest_a = pkg_a.semantic_digest() if hasattr(pkg_a, "semantic_digest") else pkg_a.digest()
    digest_b = pkg_b.semantic_digest() if hasattr(pkg_b, "semantic_digest") else pkg_b.digest()

    assert digest_a != digest_b, "Trusted observation change must alter package digest!"


def test_l4_r08_path_traversal_rejected() -> None:
    """L4-R08: Path traversal attempts in playback or verify must raise typed safe path errors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "recordings"
        root.mkdir()
        engine = ReplayEngine(root=root)

        with pytest.raises(Exception):
            engine.playback("../outside")

        with pytest.raises(Exception):
            engine.verify("../outside")


def test_l4_r09_broken_prev_hash_rejected_at_append() -> None:
    """L4-R09: Appending an entry with seq > 1 and empty prev_hash must raise JournalVerificationError immediately."""
    j = HashChainJournal()
    j.append_event("run_started", str(uuid.uuid4()), "c0", datetime.now(UTC), {})

    # Attempt to append a second entry with blank prev_hash
    e2 = JournalEntry(
        seq=2,
        id=uuid.uuid4(),
        type="tool_call",
        run_id=j.entries[0].run_id,
        correlation_id="c1",
        time=datetime.now(UTC),
        payload={"tool_name": "dummy"},
        prev_hash="",  # INVALID FOR SEQ=2
        hash="0" * 64,
    )

    with pytest.raises(JournalVerificationError):
        j.append(e2)


def test_l4_r10_recording_metadata_journal_digest_mismatch() -> None:
    """L4-R10: Mismatch between RunRecording metadata digest and actual journal digest must fail closed."""
    from flight_agent_evaluator.recording.contracts import RecordingIntegrityStatus

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "recordings"
        root.mkdir()
        store = FileRecordingStore(root)

        run_id = str(uuid.uuid4())
        journal = _create_sample_journal(run_id)
        true_digest = journal.final_digest()

        # Metadata with corrupted / mismatched final_digest
        fake_digest = hashlib.sha256(b"corrupted").hexdigest()
        summary = RunRecording(
            schema_version=1,
            run_id=uuid.UUID(run_id),
            scenario_id="jfk-lhr-delay",
            scenario_version=1,
            seed=42,
            entry_count=journal.entry_count,
            final_digest=fake_digest,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )

        store.write_recording(run_id, journal, summary)

        engine = ReplayEngine(root=root)
        report = engine.verify(run_id)

        # Must report integrity tampered/failed, and behaviour verification must NOT pass
        assert report.integrity_status in (
            RecordingIntegrityStatus.TAMPERED,
            "recording_tampered",
            "tampered",
        )
        assert report.status != "behaviour_verified"
        assert report.status != "verified"

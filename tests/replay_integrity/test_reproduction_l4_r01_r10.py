"""Red-team reproduction tests for Layer 4 Replay and Evidence Integrity.

Tests L4-R01 through L4-R10 reproduce vulnerabilities and defects present in
the baseline recording/replay and evidence infrastructure.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from flight_agent_evaluator.replay.comparator import SemanticReplayComparison
from flight_agent_evaluator.replay.engine import ReplayEngine


def _runner_journal(
    run_id: str,
    scenario_id: str = "jfk-lhr-delay",
    transform: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
) -> HashChainJournal:
    """Journal produced by the real ScenarioRunner, re-keyed to ``run_id``.

    ``transform`` may rewrite an entry payload or drop the entry (return None).
    """
    from flight_agent_evaluator.engine.runner import ScenarioRunner
    from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

    loaded = ScenarioLoader().load_from_path(Path(f"resources/scenarios/{scenario_id}.json"))
    with tempfile.TemporaryDirectory() as tmp:
        recording = asyncio.run(ScenarioRunner().run(loaded, output_dir=Path(tmp)))
        source = FileRecordingStore(Path(tmp)).read_recording(str(recording.run_id))
    j = HashChainJournal()
    for entry in source.entries:
        payload: dict[str, Any] | None = copy.deepcopy(dict(entry.payload))
        if transform is not None and payload is not None:
            payload = transform(entry.type, payload)
        if payload is None:
            continue
        j.append_event(entry.type, run_id, entry.correlation_id, entry.time, payload)
    return j


def _create_sample_journal(run_id: str) -> HashChainJournal:
    return _runner_journal(run_id)


def _compare(original: HashChainJournal, replay: HashChainJournal) -> SemanticReplayComparison:
    from flight_agent_evaluator.replay.comparator import SemanticReplayComparator
    from flight_agent_evaluator.replay.projection import project_semantic_event

    return SemanticReplayComparator().compare(
        tuple(project_semantic_event(e) for e in original.entries),
        tuple(project_semantic_event(e) for e in replay.entries),
    )


def test_l4_r01_tool_result_semantic_payload_divergence() -> None:
    """L4-R01: Divergence in a tool result payload must cause behaviour verification to fail."""
    run_id = str(uuid.uuid4())

    def _shift_delay(entry_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result")
        if entry_type == "tool_result" and isinstance(result, dict) and "status" in result:
            result["status"]["delay_minutes"] = (result["status"].get("delay_minutes") or 0) + 30
        return payload

    comparison = _compare(_runner_journal(run_id), _runner_journal(run_id, transform=_shift_delay))

    assert not comparison.verified
    assert any(d.kind == "tool_result_value_mismatch" for d in comparison.divergences)


def test_l4_r02_tool_argument_divergence() -> None:
    """L4-R02: Divergence in tool arguments must cause behaviour verification to fail."""
    run_id = str(uuid.uuid4())

    def _other_flight(entry_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if entry_type == "tool_call" and "flight_id" in payload["arguments"]:
            payload["arguments"]["flight_id"] = "AA999"
        return payload

    comparison = _compare(_runner_journal(run_id), _runner_journal(run_id, transform=_other_flight))

    assert not comparison.verified
    assert any("argument" in d.kind.value.lower() for d in comparison.divergences)


def test_l4_r03_final_response_divergence() -> None:
    """L4-R03: Divergence in final response must cause behaviour verification to fail."""
    run_id = str(uuid.uuid4())

    def _rewrite_response(entry_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if entry_type == "driver_completed":
            payload["final_response"] = "Flight is completely on time."
        return payload

    comparison = _compare(
        _runner_journal(run_id), _runner_journal(run_id, transform=_rewrite_response)
    )

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
        {"run_status": "completed", "tool_calls_made": 0},
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
        {"run_status": "completed", "tool_calls_made": 0},
    )

    events_orig = tuple(project_semantic_event(e) for e in j_orig.entries)
    events_replay = tuple(project_semantic_event(e) for e in j_replay.entries)

    comparator = SemanticReplayComparator()
    comparison = comparator.compare(events_orig, events_replay)

    assert not comparison.verified
    assert any("state" in d.kind.value.lower() for d in comparison.divergences)


def test_l4_r05_fault_divergence() -> None:
    """L4-R05: Divergence in fault injection must cause behaviour verification to fail."""
    run_id = str(uuid.uuid4())
    scenario = "jfk-lhr-timeout-recovery"
    original = _runner_journal(run_id, scenario)
    assert any(e.type == "fault_injected" for e in original.entries)

    def _change_fault(entry_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if entry_type == "fault_injected":
            payload["fault_id"] = "0" * 32
        return payload

    def _drop_fault(entry_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return None if entry_type == "fault_injected" else payload

    changed = _compare(original, _runner_journal(run_id, scenario, _change_fault))
    assert not changed.verified
    assert any(d.kind == "fault_mismatch" for d in changed.divergences)

    dropped = _compare(original, _runner_journal(run_id, scenario, _drop_fault))
    assert not dropped.verified
    assert dropped.divergences


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
        # Default (strict) verification refuses a bundle without a manifest.
        strict_report = engine.verify(run_id)
        assert strict_report.integrity_status != RecordingIntegrityStatus.VERIFIED
        assert strict_report.status not in ("behaviour_verified", "verified", "integrity_valid")

        # Lenient reading still detects the metadata/journal digest mismatch as tampering.
        report = engine.verify(run_id, strict_bundle=False)
        assert report.integrity_status == RecordingIntegrityStatus.TAMPERED
        assert report.status == "recording_tampered"

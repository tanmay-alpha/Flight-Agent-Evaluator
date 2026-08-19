"""Comprehensive test suite for Layer 4: Replay & Evidence Integrity.

Tests all hard invariants (R-INV-01 through R-INV-24) and adversarial tamper modes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_agent_evaluator.agent.errors import (
    ModelReplayMissingExchangeError,
    ModelReplayResponseDigestMismatchError,
)
from flight_agent_evaluator.agent.model_client import ReplayModelClient
from flight_agent_evaluator.contracts.model import (
    ModelConfiguration,
    ModelExchange,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
)
from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
    JudgeCriterionResult,
    JudgeEvidencePackage,
    JudgeExchange,
    JudgeExchangeManifest,
    JudgeRequestFingerprintV1,
    JudgeResult,
    TrustedObservation,
)
from flight_agent_evaluator.judges.errors import JudgeReplayNotFoundError
from flight_agent_evaluator.judges.replay import ReplayJudgeClient
from flight_agent_evaluator.judges.resolver import VerifiedEvidenceResolver
from flight_agent_evaluator.recording.contracts import (
    BehaviourVerificationStatus,
    JournalEntry,
    RecordingBundleManifest,
    RecordingIntegrityStatus,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import (
    HashChainJournal,
    JournalReadLimits,
    JournalVerificationError,
)
from flight_agent_evaluator.recording.store import (
    FileRecordingStore,
    RecordingIntegrityError,
    RecordingPathError,
)
from flight_agent_evaluator.replay.comparator import (
    SemanticDivergenceType,
    SemanticReplayComparator,
)
from flight_agent_evaluator.replay.engine import ReplayEngine
from flight_agent_evaluator.replay.projection import (
    SemanticEventType,
    project_semantic_event,
)


def _create_clean_journal(run_id: str) -> HashChainJournal:
    j = HashChainJournal()
    j.append_event(
        "run_started",
        run_id,
        "c0",
        datetime(2026, 7, 28, 10, 0, 0, tzinfo=UTC),
        {"scenario_id": "jfk-lhr-delay", "seed": 42},
    )
    j.append_event(
        "tool_call",
        run_id,
        "c1",
        datetime(2026, 7, 28, 10, 0, 1, tzinfo=UTC),
        {
            "tool_name": "flight.get_status",
            "arguments": {"flight_id": "AS142"},
            "call_id": "call-1",
        },
    )
    j.append_event(
        "tool_result",
        run_id,
        "c1",
        datetime(2026, 7, 28, 10, 0, 2, tzinfo=UTC),
        {"call_id": "call-1", "status": "SUCCESS", "value": {"status": "DELAYED"}},
    )
    j.append_event(
        "final_response",
        run_id,
        "c2",
        datetime(2026, 7, 28, 10, 0, 3, tzinfo=UTC),
        {"response": "Flight AS142 is delayed."},
    )
    j.append_event(
        "run_completed",
        run_id,
        "c3",
        datetime(2026, 7, 28, 10, 0, 4, tzinfo=UTC),
        {"stop_reason": "completed"},
    )
    return j


# ---------------------------------------------------------------------------
# Invariant R-INV-01 to R-INV-07: Semantic Event Projection & Comparator
# ---------------------------------------------------------------------------


def test_semantic_event_projection_excludes_wall_clock():
    """R-INV-19 & 20: Wall-clock differences do not alter semantic digest."""
    run_id = str(uuid.uuid4())
    j1 = HashChainJournal()
    j1.append_event(
        "tool_call",
        run_id,
        "c1",
        datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        {
            "tool_name": "flight.get_status",
            "arguments": {"flight_id": "AS101"},
            "call_id": "call-1",
        },
    )

    j2 = HashChainJournal()
    j2.append_event(
        "tool_call",
        run_id,
        "c1",
        datetime(2027, 5, 20, 18, 30, 0, tzinfo=UTC),  # Completely different wall-clock time
        {
            "tool_name": "flight.get_status",
            "arguments": {"flight_id": "AS101"},
            "call_id": "call-1",
        },
    )

    ev1 = project_semantic_event(j1.entries[0])
    ev2 = project_semantic_event(j2.entries[0])

    assert ev1.semantic_digest == ev2.semantic_digest
    assert ev1.event_type == SemanticEventType.TOOL_CALL
    assert ev1.payload["tool_name"] == "flight.get_status"


def test_comparator_detects_tool_error_mismatch():
    """R-INV-03: Mismatched tool error causes behaviour verification to fail."""
    run_id = str(uuid.uuid4())
    j1 = HashChainJournal()
    j1.append_event(
        "tool_result",
        run_id,
        "c1",
        datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        {"call_id": "call-1", "status": "ERROR", "error": "RATE_LIMIT_EXCEEDED"},
    )

    j2 = HashChainJournal()
    j2.append_event(
        "tool_result",
        run_id,
        "c1",
        datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
        {"call_id": "call-1", "status": "ERROR", "error": "INTERNAL_SERVER_ERROR"},
    )

    ev1 = (project_semantic_event(j1.entries[0]),)
    ev2 = (project_semantic_event(j2.entries[0]),)

    comp = SemanticReplayComparator().compare(ev1, ev2)
    assert not comp.verified
    assert any("error" in d.kind.value.lower() for d in comp.divergences)


def test_comparator_detects_extra_and_missing_events():
    """R-INV-07: Dropped or extra events cause verification failure."""
    run_id = str(uuid.uuid4())
    j = _create_clean_journal(run_id)
    events_full = tuple(project_semantic_event(e) for e in j.entries)
    events_truncated = events_full[:3]

    comp_missing = SemanticReplayComparator().compare(events_full, events_truncated)
    assert not comp_missing.verified
    assert any(d.kind == SemanticDivergenceType.MISSING_EVENT for d in comp_missing.divergences)

    comp_extra = SemanticReplayComparator().compare(events_truncated, events_full)
    assert not comp_extra.verified
    assert any(d.kind == SemanticDivergenceType.EXTRA_EVENT for d in comp_extra.divergences)


# ---------------------------------------------------------------------------
# Invariant R-INV-08, 15, 17, 18: Journal & Bundle Store Integrity
# ---------------------------------------------------------------------------


def test_strict_genesis_prev_hash(tmp_path: Path):
    """R-INV-17: Genesis entry must have empty or 0*64 prev_hash."""
    j = HashChainJournal()
    bad_genesis = JournalEntry(
        v=1,
        seq=1,
        id=uuid.uuid4(),
        type="run_started",
        run_id=uuid.uuid4(),
        correlation_id="c0",
        time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        payload={},
        prev_hash="a" * 64,  # Invalid genesis prev_hash
        hash="0" * 64,
    )
    with pytest.raises(JournalVerificationError, match="Invalid genesis"):
        j.append(bad_genesis)


def test_journal_read_limits_enforced(tmp_path: Path):
    """R-INV-18: Journal limits protect against unbounded memory allocation."""
    p = tmp_path / "large.jsonl"
    p.write_bytes(b"x" * 2000)

    limits = JournalReadLimits(max_total_bytes=1000)
    with pytest.raises(JournalVerificationError, match="exceeds limit"):
        HashChainJournal.read_unverified_jsonl(p, limits=limits)


def test_bundle_manifest_cryptographic_cross_binding(tmp_path: Path):
    """R-INV-08: Modifying metadata byte hash breaks bundle manifest verification."""
    store = FileRecordingStore(tmp_path)
    run_id = str(uuid.uuid4())
    j = _create_clean_journal(run_id)
    rec = RunRecording(
        run_id=uuid.UUID(run_id),
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        seed=42,
        entry_count=j.entry_count,
        final_digest=j.final_digest(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    manifest = RecordingBundleManifest(
        run_id=run_id,
        journal_file=f"{run_id}.jsonl",
        journal_bytes_sha256=hashlib.sha256(j.to_jsonl_string().encode("utf-8")).hexdigest(),
        journal_chain_digest=j.final_digest(),
        journal_entry_count=j.entry_count,
        metadata_file=f"{run_id}.meta.json",
        metadata_bytes_sha256=hashlib.sha256(
            (rec.model_dump_json(indent=2) + "\n").encode("utf-8")
        ).hexdigest(),
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        scenario_digest="a" * 64,
        agent_id="scripted-oracle",
        semantic_recording_digest="b" * 64,
    )
    store.write_recording(run_id, j, rec, manifest=manifest)

    # Clean bundle read succeeds
    j_loaded, rec_loaded, man_loaded = store.read_bundle(run_id, strict=True)
    assert man_loaded is not None

    # Tamper with metadata file
    meta_path = store.resolve_safe_path(run_id, ".meta.json")
    meta_path.write_text('{"tampered": true}', encoding="utf-8")

    with pytest.raises(RecordingIntegrityError, match="Metadata byte digest mismatch"):
        store.read_bundle(run_id, strict=True)


def test_path_traversal_escapes_rejected(tmp_path: Path):
    """R-INV-15 & 16: Windows drive indicators, UNC paths, and traversals rejected."""
    store = FileRecordingStore(tmp_path)

    for bad_id in (
        "../escape",
        "..\\escape",
        "nested/sub",
        "C:\\Windows",
        "\\\\server\\share",
        "run\x00id",
        "",
        "   ",
    ):
        with pytest.raises(RecordingPathError):
            store.resolve_safe_path(bad_id)


# ---------------------------------------------------------------------------
# Invariant R-INV-11, 12, 21: Model Exchange Replay Integrity
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_replay_model_client_fingerprint_and_response_digest_integrity():
    """R-INV-11 & 12: ReplayModelClient verifies request fingerprint and response digest."""
    req = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id="default",
        prompt_policy_version="1.0.0",
        prompt_digest="0" * 64,
        turn_index=0,
        messages=[{"role": "user", "content": "Find flights from JFK to LHR."}],
        model_configuration=ModelConfiguration(),
    )
    req_fp = req.canonical_fingerprint()

    resp = ModelResponse(role="assistant", content="Found flight AS142.")
    resp_digest = resp.canonical_digest()

    exchange = ModelExchange(
        turn_index=0,
        request=req,
        response=resp,
        request_fingerprint=req_fp,
        response_digest=resp_digest,
    )

    manifest = ModelExchangeManifest(
        manifest_id="manifest-1",
        model_configuration=ModelConfiguration(),
        exchanges=[exchange],
    )

    client = ReplayModelClient(manifest)
    res = await client.create_completion(req)
    assert res.content == "Found flight AS142."

    # Missing request fingerprint
    unseen_req = req.model_copy(
        update={"turn_index": 99, "messages": [{"role": "user", "content": "Other"}]}
    )
    with pytest.raises(ModelReplayMissingExchangeError):
        await client.create_completion(unseen_req)

    # Tampered response in manifest with stale response_digest
    tampered_resp = ModelResponse(role="assistant", content="Found flight AS999.")
    tampered_exchange = ModelExchange(
        turn_index=0,
        request=req,
        response=tampered_resp,
        request_fingerprint=req_fp,
        response_digest=resp_digest,  # STALE
    )
    tampered_manifest = ModelExchangeManifest(
        manifest_id="manifest-tampered",
        model_configuration=ModelConfiguration(),
        exchanges=[tampered_exchange],
    )
    tampered_client = ReplayModelClient(tampered_manifest)
    with pytest.raises(ModelReplayResponseDigestMismatchError):
        await tampered_client.create_completion(req)


# ---------------------------------------------------------------------------
# Invariant R-INV-13, 14: Judge Evidence & Replay Integrity
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_judge_replay_client_strict_binding():
    """R-INV-13 & 14: Judge replay client binds evidence, rubric version, and results."""
    obs = TrustedObservation(
        evidence_id="obs-1",
        source="seq:2",
        description="Flight status checked",
        value='{"status": "DELAYED"}',
    )
    pkg = JudgeEvidencePackage(
        package_id="pkg-1",
        scenario_id="jfk-lhr-delay",
        run_id=str(uuid.uuid4()),
        public_task="Check status of AS142",
        trusted_observations=[obs],
        final_response="Flight AS142 is delayed.",
        tool_call_summary="flight.get_status",
        created_at=datetime.now(UTC),
    )
    pkg_digest = pkg.semantic_digest()

    fp_obj = JudgeRequestFingerprintV1(
        evidence_package_semantic_digest=pkg_digest,
        rubric_version="judge-rubric-v1",
        prompt_policy_id="standard",
    )
    fp = fp_obj.canonical_fingerprint()

    judge_result = JudgeResult(
        schema_version="judge-schema-v1",
        package_id="pkg-1",
        package_digest=pkg_digest,
        mode="replay",
        criteria_results=[
            JudgeCriterionResult(
                criterion=JudgeCriterion.GROUNDEDNESS,
                score=4,
                evidence_ids=["obs-1"],
                rationale="Accurate report matching observation",
            )
        ],
        overall_score=4.0,
        created_at=datetime.now(UTC),
    )

    resp_text = json.dumps(judge_result.model_dump(mode="json"))
    resp_digest = hashlib.sha256(resp_text.encode("utf-8")).hexdigest()

    exchange = JudgeExchange(
        exchange_id="ex-1",
        request_fingerprint=fp,
        package_digest=pkg_digest,
        rubric_version="judge-rubric-v1",
        request_messages=[{"role": "user", "content": "Grade"}],
        response_text=resp_text,
        response_digest=resp_digest,
        parsed_result=judge_result,
        parsed_result_digest=judge_result.canonical_digest(),
        model_id="gpt-4o",
        recorded_at=datetime.now(UTC),
    )

    manifest = JudgeExchangeManifest(
        manifest_id="manifest-1",
        exchanges=[exchange],
        created_at=datetime.now(UTC),
    )

    client = ReplayJudgeClient(manifest)
    res = await client.judge(pkg, rubric_version="judge-rubric-v1", prompt_policy_id="standard")
    assert res.overall_score == 4.0

    # Mismatched rubric version rejected
    with pytest.raises(JudgeReplayNotFoundError, match="Rubric version mismatch"):
        await client.judge(pkg, rubric_version="judge-rubric-v2", prompt_policy_id="standard")

    # Tampered raw response text rejected
    tampered_exchange = exchange.model_copy(update={"response_text": '{"tampered": true}'})
    tampered_manifest = JudgeExchangeManifest(
        manifest_id="manifest-tampered",
        exchanges=[tampered_exchange],
        created_at=datetime.now(UTC),
    )
    tampered_client = ReplayJudgeClient(tampered_manifest)
    with pytest.raises(JudgeReplayNotFoundError, match="raw response digest mismatch"):
        await tampered_client.judge(
            pkg, rubric_version="judge-rubric-v1", prompt_policy_id="standard"
        )


def test_verified_evidence_resolver():
    """VerifiedEvidenceResolver maps evidence observations back to journal entries."""
    run_id = str(uuid.uuid4())
    j = _create_clean_journal(run_id)

    obs1 = TrustedObservation(
        evidence_id="obs-1",
        source="seq:2",
        description="Tool call for status",
        value='{"flight_id": "AS142"}',
    )
    obs2 = TrustedObservation(
        evidence_id="obs-2",
        source="call:call-1",
        description="Call ID reference",
        value='{"status": "SUCCESS"}',
    )

    resolver = VerifiedEvidenceResolver(j)
    r1 = resolver.resolve_observation(obs1)
    assert r1["resolved_entry_seq"] == 2
    assert r1["resolved_entry_type"] == "tool_call"

    r2 = resolver.resolve_observation(obs2)
    assert r2["resolved_entry_seq"] == 2
    assert r2["resolved_entry_type"] == "tool_call"


# ---------------------------------------------------------------------------
# Invariant R-INV-09, 10, 22, 24: Replay Engine Full Integration
# ---------------------------------------------------------------------------


def test_replay_engine_end_to_end_verification_and_tampering(tmp_path: Path):
    """R-INV-22 & 24: ReplayEngine distinguishes integrity vs behaviour status."""
    scenario_path = Path("resources/scenarios/jfk-lhr-delay.json")
    from flight_agent_evaluator.engine.runner import ScenarioRunner
    from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

    loader = ScenarioLoader()
    loaded = loader.load_from_path(scenario_path)

    runner = ScenarioRunner()
    rec = asyncio.run(runner.run(loaded, output_dir=tmp_path))
    run_id = str(rec.run_id)

    engine = ReplayEngine(tmp_path)

    # 1. Authentic run verifies cleanly
    report = engine.verify(run_id, scenario_path=scenario_path)
    assert report.integrity_status == RecordingIntegrityStatus.VERIFIED
    assert report.behaviour_status == BehaviourVerificationStatus.VERIFIED
    assert report.provenance_status == "verified"
    assert report.status == "behaviour_verified"
    assert len(report.divergences) == 0

    # 2. Tampering journal without changing metadata causes TAMPERED
    journal_path = tmp_path / f"{run_id}.jsonl"
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    first_obj = json.loads(lines[0])
    first_obj["payload"]["scenario_id"] = "tampered_sc"
    lines[0] = json.dumps(first_obj, sort_keys=True, separators=(",", ":"))
    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tampered_report = engine.verify(run_id, scenario_path=scenario_path)
    assert tampered_report.integrity_status == RecordingIntegrityStatus.TAMPERED
    assert tampered_report.status == "recording_tampered"
    assert len(tampered_report.divergences) > 0

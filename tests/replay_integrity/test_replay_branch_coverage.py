"""Targeted branch coverage tests for Layer 4: Replay & Evidence Integrity."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
    JudgeCriterionResult,
    JudgeEvidencePackage,
    JudgeExchange,
    JudgeExchangeManifest,
    JudgeResult,
)
from flight_agent_evaluator.judges.errors import (
    JudgeReplayCorruptedError,
)
from flight_agent_evaluator.judges.replay import ReplayJudgeClient
from flight_agent_evaluator.recording.contracts import (
    RecordingBundleManifest,
    ReplayProvenance,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import (
    HashChainJournal,
)
from flight_agent_evaluator.recording.store import (
    FileRecordingStore,
    RecordingIntegrityError,
    RecordingPathError,
)
from flight_agent_evaluator.replay.comparator import (
    SemanticReplayComparator,
)
from flight_agent_evaluator.replay.projection import (
    SemanticEventType,
    SemanticJournalEvent,
    compute_semantic_recording_digest,
)
from flight_agent_evaluator.replay.provenance import (
    ReplayExecutionFactory,
    ReplayProvenanceMismatchError,
    ReplayUnavailableError,
    extract_provenance,
)


def test_provenance_mismatch_branches(tmp_path: Path):
    """Cover mismatch checks in extract_provenance."""
    run_id = str(uuid.uuid4())
    j = HashChainJournal()
    j.append_event(
        "run_started",
        run_id,
        "c0",
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        {"scenario_id": "sc1", "seed": 42},
    )
    rec = RunRecording(
        run_id=uuid.UUID(run_id),
        scenario_id="sc1",
        scenario_version=1,
        seed=42,
        entry_count=1,
        final_digest=j.final_digest(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    # Missing scenario_id when recording is None and journal has no scenario_id
    j_empty = HashChainJournal()
    j_empty.append_event(
        "driver_started", run_id, "c0", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC), {}
    )
    with pytest.raises(ReplayUnavailableError, match="Cannot determine scenario_id"):
        extract_provenance(None, j_empty)

    # Manifest scenario_id mismatch
    manifest_mismatch = RecordingBundleManifest(
        run_id=run_id,
        journal_file=f"{run_id}.jsonl",
        journal_bytes_sha256="0" * 64,
        journal_chain_digest=j.final_digest(),
        journal_entry_count=1,
        metadata_file=f"{run_id}.meta.json",
        metadata_bytes_sha256="0" * 64,
        scenario_id="different_scenario",
        scenario_version=1,
        scenario_digest="0" * 64,
        agent_id="oracle",
        semantic_recording_digest="0" * 64,
    )
    prov_manifest = extract_provenance(rec, j, manifest=manifest_mismatch)
    assert prov_manifest.scenario_id == "different_scenario"


def test_replay_factory_resolution_branches(tmp_path: Path):
    """Cover error paths in ReplayExecutionFactory."""

    factory = ReplayExecutionFactory(resource_root=tmp_path)
    prov = ReplayProvenance(
        scenario_id="missing_sc",
        scenario_version=1,
        scenario_digest="",
        seed=42,
        agent_id="unknown_agent",
    )

    # Missing scenario file
    with pytest.raises(ReplayUnavailableError, match="not found"):
        factory.resolve_scenario(prov, explicit_path=tmp_path / "missing.json")

    # Invalid JSON scenario
    bad_sc = tmp_path / "bad.json"
    bad_sc.write_text("invalid json", encoding="utf-8")
    with pytest.raises((ReplayUnavailableError, Exception)):
        factory.resolve_scenario(prov, explicit_path=bad_sc)

    # Scenario digest mismatch
    sc_src = Path("resources/scenarios/jfk-lhr-delay.json").read_text(encoding="utf-8")
    sc_file = tmp_path / "sc_digest_test.json"
    sc_file.write_text(sc_src, encoding="utf-8")

    prov_with_digest = prov.model_copy(
        update={"scenario_id": "jfk-lhr-delay", "scenario_digest": "0" * 64}  # Bad digest
    )
    with pytest.raises(ReplayProvenanceMismatchError, match="digest mismatch"):
        factory.resolve_scenario(prov_with_digest, explicit_path=sc_file)

    # Unknown agent
    with pytest.raises(ReplayUnavailableError, match="Cannot resolve agent"):
        factory.resolve_agent(prov)


def test_recording_store_bundle_branches(tmp_path: Path):
    """Cover extra branches in FileRecordingStore."""
    store = FileRecordingStore(tmp_path)
    run_id = str(uuid.uuid4())
    j = HashChainJournal()
    j.append_event("run_started", run_id, "c0", datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC), {})
    rec = RunRecording(
        run_id=uuid.UUID(run_id),
        scenario_id="sc1",
        scenario_version=1,
        seed=42,
        entry_count=1,
        final_digest=j.final_digest(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    j_bytes = j.to_jsonl_string().encode("utf-8")
    m_bytes = (rec.model_dump_json(indent=2) + "\n").encode("utf-8")

    man = RecordingBundleManifest(
        run_id=run_id,
        journal_file=f"{run_id}.jsonl",
        journal_bytes_sha256=hashlib.sha256(j_bytes).hexdigest(),
        journal_chain_digest=j.final_digest(),
        journal_entry_count=1,
        metadata_file=f"{run_id}.meta.json",
        metadata_bytes_sha256=hashlib.sha256(m_bytes).hexdigest(),
        scenario_id="sc1",
        scenario_version=1,
        scenario_digest="0" * 64,
        agent_id="scripted",
        semantic_recording_digest="0" * 64,
    )
    store.write_recording(run_id, j, rec, manifest=man)
    assert store.resolve_safe_path(run_id, ".bundle.json").is_file()

    # read_bundle_manifest
    loaded_man = store.read_bundle_manifest(run_id)
    assert loaded_man.run_id == run_id

    # read_bundle strict journal chain digest mismatch
    bad_manifest = man.model_copy(update={"journal_chain_digest": "0" * 64})
    man_path = store.resolve_safe_path(run_id, ".bundle.json")
    man_path.write_text(bad_manifest.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(RecordingIntegrityError, match="Chain digest mismatch"):
        store.read_bundle(run_id, strict=True)

    # write_recording with invalid target
    with pytest.raises(RecordingPathError):
        store.write_recording("../bad", j, rec)


def test_projection_and_comparator_extra_branches():
    """Cover error types and edge cases in projection and comparator."""
    # SemanticJournalEvent creation
    ev = SemanticJournalEvent(
        sequence=1,
        event_type=SemanticEventType.STATE_SNAPSHOT,
        payload={"state": {"key": "val"}},
        semantic_digest="0" * 64,
    )
    assert ev.event_type == SemanticEventType.STATE_SNAPSHOT

    # compute_semantic_recording_digest empty
    empty_digest = compute_semantic_recording_digest(())
    assert len(empty_digest) == 64

    # Comparator with max_divergences cap
    events_a = tuple(
        SemanticJournalEvent(
            sequence=i,
            event_type=SemanticEventType.TOOL_CALL,
            payload={"tool_name": f"tool_{i}"},
            semantic_digest=f"{i}" * 64,
        )
        for i in range(10)
    )
    events_b = tuple(
        SemanticJournalEvent(
            sequence=i,
            event_type=SemanticEventType.TOOL_CALL,
            payload={"tool_name": f"other_tool_{i}"},
            semantic_digest=f"{i + 10}" * 64,
        )
        for i in range(10)
    )

    comp = SemanticReplayComparator(max_divergences=3).compare(events_a, events_b)
    assert len(comp.divergences) == 3


@pytest.mark.anyio
async def test_judge_replay_manifest_validation():
    """Cover manifest validation in ReplayJudgeClient."""
    # Invalid exchanges list type
    with pytest.raises(JudgeReplayCorruptedError, match="Invalid manifest"):
        ReplayJudgeClient("not a manifest")  # type: ignore[arg-type]

    # Duplicate fingerprints in exchanges
    pkg = JudgeEvidencePackage(
        package_id="p1",
        scenario_id="s1",
        run_id=str(uuid.uuid4()),
        public_task="task",
        trusted_observations=[],
        final_response="resp",
        created_at=datetime.now(UTC),
    )
    judge_res = JudgeResult(
        schema_version="judge-schema-v1",
        package_id="p1",
        package_digest=pkg.semantic_digest(),
        mode="replay",
        criteria_results=[
            JudgeCriterionResult(
                criterion=JudgeCriterion.GROUNDEDNESS,
                score=3,
                rationale="Grounded observation",
            )
        ],
        overall_score=3.0,
        created_at=datetime.now(UTC),
    )
    resp_text = json.dumps(judge_res.model_dump(mode="json"))
    ex1 = JudgeExchange(
        exchange_id="ex-1",
        request_fingerprint="fp-dup",
        package_digest=pkg.semantic_digest(),
        rubric_version="v1",
        request_messages=[],
        response_text=resp_text,
        response_digest=hashlib.sha256(resp_text.encode("utf-8")).hexdigest(),
        parsed_result=judge_res,
        parsed_result_digest=judge_res.canonical_digest(),
        model_id="gpt-4o",
        recorded_at=datetime.now(UTC),
    )
    ex2 = ex1.model_copy(update={"exchange_id": "ex-2"})

    manifest = JudgeExchangeManifest(
        manifest_id="m-dup",
        exchanges=[ex1, ex2],
        created_at=datetime.now(UTC),
    )
    with pytest.raises(JudgeReplayCorruptedError, match="Duplicate request fingerprint"):
        ReplayJudgeClient(manifest)

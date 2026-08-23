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

    # Modify tool call in journal with valid internal hash chain and matching summary
    store = FileRecordingStore(tmp_path)
    journal = store.read_recording(str(rec.run_id))

    journal.append_event(
        "tool_call",
        run_id=str(rec.run_id),
        correlation_id="tamper",
        time=datetime.now(UTC).isoformat(),
        payload={"tool_name": "extra.tool", "call_id": "extra-1"},
    )
    rec_updated = rec.model_copy(
        update={"final_digest": journal.final_digest(), "entry_count": journal.entry_count}
    )
    manifest = store.read_bundle_manifest(str(rec.run_id))
    import hashlib

    journal_bytes = journal.to_jsonl_string().encode("utf-8")
    meta_bytes = (rec_updated.model_dump_json(indent=2) + "\n").encode("utf-8")
    manifest_updated = manifest.model_copy(
        update={
            "journal_bytes_sha256": hashlib.sha256(journal_bytes).hexdigest(),
            "journal_chain_digest": journal.final_digest(),
            "journal_entry_count": journal.entry_count,
            "metadata_bytes_sha256": hashlib.sha256(meta_bytes).hexdigest(),
            "semantic_recording_digest": hashlib.sha256(
                (journal.final_digest() + manifest.scenario_digest).encode("utf-8")
            ).hexdigest(),
        }
    )
    store.write_recording(str(rec.run_id), journal, rec_updated, manifest=manifest_updated)

    engine = ReplayEngine(tmp_path)
    report = engine.verify(str(rec.run_id), scenario_path=scenario_path)
    assert report.status == "behaviour_diverged"
    assert len(report.divergences) > 0


def test_replay_provenance_journal_fallback():
    import pytest

    from flight_agent_evaluator.replay.provenance import (
        ReplayExecutionFactory,
        ReplayProvenance,
        ReplayProvenanceMismatchError,
        ReplayUnavailableError,
        extract_provenance,
    )

    journal = HashChainJournal()
    valid_run_id = str(uuid.uuid4())
    journal.append_event(
        "run_started",
        run_id=valid_run_id,
        correlation_id="c1",
        time=datetime.now(UTC).isoformat(),
        payload={
            "scenario_id": "jfk-lhr-delay",
            "seed": 42,
            "scenario_version": 1,
            "agent_id": "naive-baseline",
        },
    )
    prov = extract_provenance(recording=None, journal=journal)
    assert prov.scenario_id == "jfk-lhr-delay"
    assert prov.agent_id == "naive-baseline"
    assert prov.seed == 42

    # Empty journal raises
    empty_journal = HashChainJournal()
    with pytest.raises(ReplayUnavailableError):
        extract_provenance(recording=None, journal=empty_journal)

    # Factory agent resolution
    factory = ReplayExecutionFactory()
    custom = object()
    assert factory.resolve_agent(prov, custom_driver=custom) is custom

    from flight_agent_evaluator.agent.baselines import NaiveBaselineAgent

    agent = factory.resolve_agent(prov)
    assert isinstance(agent, NaiveBaselineAgent)

    prov_oracle = ReplayProvenance(
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        scenario_digest="",
        agent_id="scripted-oracle",
        seed=42,
    )
    from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver

    assert isinstance(factory.resolve_agent(prov_oracle), ScriptedAgentDriver)

    prov_model = ReplayProvenance(
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        scenario_digest="",
        agent_id="model",
        seed=42,
    )
    with pytest.raises(ReplayUnavailableError, match="requires a valid ModelExchangeManifest"):
        factory.resolve_agent(prov_model)

    from flight_agent_evaluator.contracts.model import ModelConfiguration, ModelExchangeManifest

    mem = ModelExchangeManifest(
        manifest_id="m1", model_configuration=ModelConfiguration(), exchanges=[]
    )
    from flight_agent_evaluator.agent.model_client import ReplayModelClient

    assert isinstance(
        factory.resolve_agent(prov_model, model_exchange_manifest=mem), ReplayModelClient
    )

    prov_unknown = ReplayProvenance(
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        scenario_digest="",
        agent_id="unknown-agent",
        seed=42,
    )
    with pytest.raises(ReplayUnavailableError):
        factory.resolve_agent(prov_unknown)

    # Factory scenario resolution
    sc_loaded = factory.resolve_scenario(prov)
    assert sc_loaded.scenario.scenario_id.id == "jfk-lhr-delay"

    # Digest mismatch
    prov_bad_digest = ReplayProvenance(
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        agent_id="oracle",
        seed=42,
        scenario_digest="0" * 64,
    )
    with pytest.raises(ReplayProvenanceMismatchError):
        factory.resolve_scenario(prov_bad_digest)

    # Resource root
    factory_res = ReplayExecutionFactory(resource_root=Path("resources"))
    runner = factory_res.create_runner()
    assert runner is not None

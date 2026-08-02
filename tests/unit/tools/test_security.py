"""Security tests for the Phase 2 runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from flight_agent_evaluator.engine.scenario_loader import (
    ScenarioLoader,
    ScenarioLoaderError,
)
from flight_agent_evaluator.recording.contracts import RunRecording
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import (
    FileRecordingStore,
    RecordingStoreError,
)


def test_path_traversal_rejected(tmp_path: Path):
    loader = ScenarioLoader(allowed_root=tmp_path)
    with pytest.raises(ScenarioLoaderError, match="outside"):
        loader.load_from_path(tmp_path.parent / "escape.json")


def test_run_id_traversal_rejected(tmp_path: Path):
    """Run IDs that look like paths must be rejected by the store."""
    import uuid

    store = FileRecordingStore(tmp_path)
    journal = HashChainJournal()
    journal.append_event(
        entry_type="run_started",
        run_id=str(uuid.uuid4()),
        correlation_id="c",
        time=datetime.now(UTC),
        payload={},
    )
    recording = RunRecording(
        run_id=uuid.uuid4(),
        scenario_id="x",
        scenario_version=1,
        seed=0,
        entry_count=journal.entry_count,
        final_digest=journal.final_digest(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    with pytest.raises(RecordingStoreError):
        store.write_recording("..\\evil", journal, recording)


def test_bom_in_scenario_rejected(tmp_path: Path):
    target = tmp_path / "scenario.json"
    target.write_bytes(b"\xef\xbb\xbf{}")
    loader = ScenarioLoader()
    with pytest.raises(ScenarioLoaderError, match="BOM"):
        loader.load_from_path(target)


def test_unknown_tool_returns_error(tmp_path: Path):
    """Calling an unregistered tool produces a typed error result."""
    from flight_agent_evaluator.engine.fault_engine import FaultEngine
    from flight_agent_evaluator.engine.tool_executor import ToolExecutor
    from flight_agent_evaluator.tools.base import ToolRegistry

    executor = ToolExecutor(registry=ToolRegistry(), faults=FaultEngine(()))
    import uuid

    from flight_agent_evaluator.contracts.tools import ToolCall
    from flight_agent_evaluator.runtime.clock import VirtualClock
    from flight_agent_evaluator.runtime.context import RunContext
    from flight_agent_evaluator.runtime.ids import DeterministicIdFactory

    clock = VirtualClock()
    id_factory = DeterministicIdFactory(scenario_id="x", scenario_version=1, seed=0)
    context = RunContext(
        run_id=uuid.uuid4(),
        scenario_id="x",
        scenario_version=1,
        seed=0,
        clock=clock,
        id_factory=id_factory,
        tool_call_limit=10,
        time_limit_seconds=60,
        correlation_id="c",
        scenario_digest="d",
        trajectory_digest="t",
    )
    import asyncio

    call = ToolCall(
        call_id=uuid.uuid4(),
        run_id=context.run_id,
        tool_name="not.a.real.tool",
        arguments={},
        start_time=context.clock.now(),
    )
    result = asyncio.run(executor.execute(call, provider=None, context=context))
    assert result.status == "failure"
    assert result.error is not None


def test_file_recording_store_sanitisation_and_missing_file(tmp_path: Path):
    store = FileRecordingStore(tmp_path)
    with pytest.raises(RecordingStoreError, match="not found"):
        store.read_recording("missing-run-id")

    with pytest.raises(RecordingStoreError, match="must not be empty"):
        store._sanitise_run_id("")

    with pytest.raises(RecordingStoreError, match="Invalid run_id"):
        store._sanitise_run_id(".")

    with pytest.raises(RecordingStoreError, match="Invalid run_id"):
        store._sanitise_run_id("..")

"""Replay verification compares what the runtime actually journals."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from flight_agent_evaluator.contracts.aviation import FlightStatusObservation, FlightStatusQuery
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.contracts import BehaviourVerificationStatus
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.replay.comparator import SemanticReplayComparator
from flight_agent_evaluator.replay.engine import ReplayEngine
from flight_agent_evaluator.replay.projection import project_semantic_event

SCENARIO = Path("resources/scenarios/jfk-lhr-delay.json")


class _ShiftedDelayProvider(FixtureFlightProvider):
    """Fixture provider whose flight-status delay differs from the packaged fixture."""

    async def get_flight_status(self, query: FlightStatusQuery) -> FlightStatusObservation:
        observation = await super().get_flight_status(query)
        status = observation.status.model_copy(
            update={"delay_minutes": (observation.status.delay_minutes or 0) + 15}
        )
        return observation.model_copy(update={"status": status})


def _record(tmp_path: Path) -> str:
    loaded = ScenarioLoader().load_from_path(SCENARIO)
    recording = asyncio.run(ScenarioRunner().run(loaded, output_dir=tmp_path))
    return str(recording.run_id)


def test_unchanged_reexecution_verifies(tmp_path: Path) -> None:
    run_id = _record(tmp_path)
    report = ReplayEngine(tmp_path).verify(run_id, scenario_path=SCENARIO)
    assert report.behaviour_status == BehaviourVerificationStatus.VERIFIED


def test_changed_tool_output_value_is_detected(tmp_path: Path) -> None:
    run_id = _record(tmp_path)
    report = ReplayEngine(tmp_path).verify(
        run_id, scenario_path=SCENARIO, provider=_ShiftedDelayProvider()
    )
    assert report.behaviour_status == BehaviourVerificationStatus.DIVERGED
    assert any(d.kind == "tool_result_value_mismatch" for d in report.divergences)


def _journal(payloads: list[tuple[str, dict[str, Any]]]) -> HashChainJournal:
    journal = HashChainJournal()
    for idx, (entry_type, payload) in enumerate(payloads):
        journal.append_event(
            entry_type,
            run_id="00000000-0000-0000-0000-000000000001",
            correlation_id="c",
            time=datetime(2026, 1, 1, 12, 0, idx, tzinfo=UTC),
            payload=payload,
        )
    return journal


_BASE: list[tuple[str, dict[str, Any]]] = [
    ("tool_call", {"call_id": "c1", "tool_name": "flight.get_status", "arguments": {}}),
    ("fault_injected", {"call_id": "c1", "fault_type": "delayed_response", "delay_seconds": 5}),
    ("tool_result", {"call_id": "c1", "status": "success", "result": {"delay_minutes": 60}}),
    ("domain_event", {"call_id": "c1", "event_type": "duplicated_event", "result": {"n": 1}}),
    ("driver_completed", {"final_response": "ok", "error": None}),
    ("run_completed", {"tool_calls_made": 1, "run_status": "completed"}),
]


@pytest.mark.parametrize(
    ("index", "changed"),
    [
        (1, {"call_id": "c1", "fault_type": "delayed_response", "delay_seconds": 50}),
        (2, {"call_id": "c1", "status": "success", "result": {"delay_minutes": 0}}),
        (3, {"call_id": "c1", "event_type": "duplicated_event", "result": {"n": 2}}),
        (4, {"final_response": "ok", "error": "RuntimeError: boom"}),
        (5, {"tool_calls_made": 1, "run_status": "error"}),
    ],
    ids=["fault-parameters", "tool-result", "domain-event-data", "driver-error", "run-status"],
)
def test_divergent_written_fields_do_not_verify(index: int, changed: dict[str, Any]) -> None:
    divergent = list(_BASE)
    divergent[index] = (divergent[index][0], changed)
    original = [project_semantic_event(e) for e in _journal(_BASE).entries]
    replay = [project_semantic_event(e) for e in _journal(divergent).entries]
    comparison = SemanticReplayComparator().compare(original, replay)
    assert not comparison.verified
    assert comparison.divergences

"""Unit tests for building ObservedTrajectory from trusted journal records."""

from __future__ import annotations

import datetime
import uuid

from flight_agent_evaluator.contracts.tools import ToolCall, ToolResult
from flight_agent_evaluator.evaluation.observation import (
    extract_observed_trajectory,
)
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock


def test_extract_observed_trajectory_from_journal():
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    journal = HashChainJournal()
    run_id = str(uuid.uuid4())
    call_id = uuid.uuid4()
    t0 = clock.now()

    tc = ToolCall(
        call_id=call_id,
        run_id=uuid.UUID(run_id),
        tool_name="flight.get_status",
        arguments={"flight_id": "AS142", "operating_day": "2026-07-28"},
        mutation_class="read_only",
        start_time=t0,
    )
    tr = ToolResult(
        call_id=call_id,
        status="success",
        result={"status": "delayed"},
        end_time=t0,
    )

    journal.append_event(
        "tool_call", run_id=run_id, correlation_id="c1", time=t0, payload=tc.model_dump(mode="json")
    )
    journal.append_event(
        "tool_result",
        run_id=run_id,
        correlation_id="c1",
        time=t0,
        payload=tr.model_dump(mode="json"),
    )

    obs_traj = extract_observed_trajectory(
        scenario_id="jfk-lhr-delay",
        run_id=run_id,
        journal=journal,
        final_response="Flight AS142 is delayed.",
    )

    assert obs_traj.scenario_id == "jfk-lhr-delay"
    assert len(obs_traj.actions) == 1
    action = obs_traj.actions[0]
    assert action.tool_name == "flight.get_status"
    assert action.arguments["flight_id"] == "AS142"
    assert action.result == {"status": "delayed"}
    assert action.mutation_class == "read_only"
    assert obs_traj.final_response == "Flight AS142 is delayed."

"""Unit tests for TrajectoryEvaluator and Scorecard calculation."""

from __future__ import annotations

import datetime
import uuid

from flight_agent_evaluator.contracts.evaluation import ToolCalledAssertion
from flight_agent_evaluator.contracts.scenarios import (
    BenchmarkScenario,
    ScenarioIdentifier,
    ScenarioLimits,
    ScenarioMetadata,
    ScenarioStep,
)
from flight_agent_evaluator.contracts.tools import ToolCall, ToolResult
from flight_agent_evaluator.contracts.trajectory_expectation import (
    ActionSelector,
    ArgumentConstraint,
    ExpectedAction,
    TrajectoryExpectation,
    ValidPath,
)
from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
from flight_agent_evaluator.recording.contracts import (
    InvokeToolStep,
    ScriptedTrajectory,
)
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock


def test_trajectory_evaluator_end_to_end():
    scenario = BenchmarkScenario(
        scenario_id=ScenarioIdentifier(id="jfk-lhr-delay", version=1),
        metadata=ScenarioMetadata(
            title="JFK to LHR Delay",
            description="Flight AS142 is delayed",
            objective="Check status",
        ),
        steps=(ScenarioStep(step_id="step1", description="Check status"),),
        limits=ScenarioLimits(tool_call_limit=5, time_limit_seconds=60),
        assertions=(ToolCalledAssertion(tool_name="flight.get_status"),),
        trajectory=ScriptedTrajectory(
            trajectory_id="t1",
            description="Golden trace",
            steps=(
                InvokeToolStep(
                    step_id="s1",
                    tool_name="flight.get_status",
                    arguments={"flight_id": "AS142"},
                ),
            ),
        ),
    )

    exp_node = ExpectedAction(
        node_id="check_status",
        selector=ActionSelector(
            tool_name="flight.get_status",
            argument_constraints=[
                ArgumentConstraint(field_pointer="/flight_id", operator="equals", value="AS142")
            ],
        ),
    )
    path = ValidPath(path_id="path_direct", expected_actions=[exp_node])
    expectation = TrajectoryExpectation(scenario_id="jfk-lhr-delay", valid_paths=[path])

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
        result={"flight_id": "AS142", "status": "delayed"},
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

    evaluator = TrajectoryEvaluator()
    scorecard = evaluator.evaluate(
        scenario=scenario,
        expectation=expectation,
        journal=journal,
        run_id=run_id,
        final_response="Flight AS142 is delayed.",
    )

    assert scorecard.overall_pass
    assert scorecard.safety_pass
    assert scorecard.selected_path_id == "path_direct"
    assert scorecard.tool_f1 == 1.0
    assert scorecard.argument_correctness_score == 1.0
    assert scorecard.composite_score > 0.8
    assert len(scorecard.evidence_attribution) == 1


def test_is_path_applicable():
    from flight_agent_evaluator.contracts.trajectory_expectation import PathCondition
    from flight_agent_evaluator.evaluation.observation import ObservedTrajectory
    from flight_agent_evaluator.evaluation.trajectory_evaluator import is_path_applicable

    cond1 = PathCondition(field_pointer="/pnr_type", operator="equals", value="vip")
    cond2 = PathCondition(field_pointer="/tier", operator="not_equals", value="standard")
    cond3 = PathCondition(field_pointer="/category", operator="one_of", value=["A", "B"])
    cond4 = PathCondition(field_pointer="/active", operator="boolean", value=True)

    dummy_act = ExpectedAction(node_id="dummy", selector=ActionSelector(tool_name="dummy_tool"))
    path1 = ValidPath(path_id="p1", expected_actions=[dummy_act], applicability_conditions=[cond1])
    path2 = ValidPath(path_id="p2", expected_actions=[dummy_act], applicability_conditions=[cond2])
    path3 = ValidPath(path_id="p3", expected_actions=[dummy_act], applicability_conditions=[cond3])
    path4 = ValidPath(path_id="p4", expected_actions=[dummy_act], applicability_conditions=[cond4])

    obs = ObservedTrajectory(scenario_id="s", run_id="r")

    assert is_path_applicable(path1, obs, initial_state={"pnr_type": "vip"})
    assert not is_path_applicable(path1, obs, initial_state={"pnr_type": "regular"})

    assert is_path_applicable(path2, obs, initial_state={"tier": "gold"})
    assert not is_path_applicable(path2, obs, initial_state={"tier": "standard"})

    assert is_path_applicable(path3, obs, initial_state={"category": "A"})
    assert not is_path_applicable(path3, obs, initial_state={"category": "C"})

    assert is_path_applicable(path4, obs, initial_state={"active": True})
    assert not is_path_applicable(path4, obs, initial_state={"active": False})

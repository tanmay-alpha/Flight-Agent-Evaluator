"""Counterexample test suite for Stage 2 Evaluator Validity (Gate 27)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from flight_agent_evaluator.contracts.json_pointer import MISSING, resolve_json_pointer
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
    PathCondition,
    SafetyConstraint,
    ScoringProfile,
    TrajectoryExpectation,
    ValidPath,
)
from flight_agent_evaluator.evaluation.matcher import (
    DeterministicBoundedMatcher,
    evaluate_argument_constraint,
)
from flight_agent_evaluator.evaluation.trajectory_evaluator import (
    TrajectoryEvaluator,
    is_path_applicable,
)
from flight_agent_evaluator.recording.contracts import InvokeToolStep, ScriptedTrajectory
from flight_agent_evaluator.recording.journal import HashChainJournal


def create_empty_journal(run_id: str | None = None) -> HashChainJournal:
    r_id = run_id or str(uuid.uuid4())
    journal = HashChainJournal()
    journal.append_event(
        entry_type="run_started",
        run_id=r_id,
        correlation_id="corr-1",
        time=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        payload={"msg": "start"},
    )
    return journal


def create_dummy_scenario() -> BenchmarkScenario:
    return BenchmarkScenario(
        scenario_id=ScenarioIdentifier(id="test-sc", version=1),
        metadata=ScenarioMetadata(title="Test", description="Test", objective="Obj"),
        limits=ScenarioLimits(tool_call_limit=5, time_limit_seconds=60),
        steps=(ScenarioStep(step_id="step-1", description="Step 1"),),
        trajectory=ScriptedTrajectory(
            trajectory_id="dummy-traj",
            description="dummy",
            steps=(InvokeToolStep(step_id="step-1", tool_name="tool.dummy", arguments={}),),
        ),
    )


def test_optional_match_cannot_make_score_exceed_1():
    req_node = ExpectedAction(
        node_id="req1",
        selector=ActionSelector(tool_name="tool.req"),
        required=True,
    )
    opt_node = ExpectedAction(
        node_id="opt1",
        selector=ActionSelector(tool_name="tool.opt"),
        required=False,
    )
    path = ValidPath(path_id="p1", expected_actions=[req_node, opt_node])
    expectation = TrajectoryExpectation(scenario_id="test-sc", valid_paths=[path])
    evaluator = TrajectoryEvaluator()
    journal = create_empty_journal()

    scorecard = evaluator.evaluate(
        scenario=create_dummy_scenario(),
        expectation=expectation,
        journal=journal,
        run_id=str(uuid.uuid4()),
    )
    assert scorecard.outcome_score <= 1.0
    assert scorecard.composite_score <= 1.0
    assert scorecard.tool_precision <= 1.0
    assert scorecard.required_recall <= 1.0


def test_required_action_completely_missing_cannot_overall_pass():
    req_node = ExpectedAction(
        node_id="req1",
        selector=ActionSelector(tool_name="tool.req"),
        required=True,
    )
    path = ValidPath(path_id="p1", expected_actions=[req_node])
    expectation = TrajectoryExpectation(scenario_id="test-sc", valid_paths=[path])
    evaluator = TrajectoryEvaluator()
    journal = create_empty_journal()

    scorecard = evaluator.evaluate(
        scenario=create_dummy_scenario(),
        expectation=expectation,
        journal=journal,
        run_id=str(uuid.uuid4()),
    )
    assert scorecard.overall_pass is False


def test_zero_applicable_paths_produces_evaluator_error():
    req_node = ExpectedAction(
        node_id="req1",
        selector=ActionSelector(tool_name="tool.req"),
        required=True,
    )
    path = ValidPath(
        path_id="p1",
        expected_actions=[req_node],
        applicability_conditions=[
            PathCondition(field_pointer="/env", operator="equals", value="production")
        ],
    )
    expectation = TrajectoryExpectation(scenario_id="test-sc", valid_paths=[path])
    evaluator = TrajectoryEvaluator()
    journal = create_empty_journal()

    scorecard = evaluator.evaluate(
        scenario=create_dummy_scenario(),
        expectation=expectation,
        journal=journal,
        run_id=str(uuid.uuid4()),
        initial_state={"env": "staging"},
    )
    assert scorecard.overall_pass is False
    assert scorecard.evaluator_error == "no_applicable_path"


def test_complexity_limit_produces_evaluator_error():
    req_node = ExpectedAction(
        node_id="req1",
        selector=ActionSelector(tool_name="tool.req"),
        required=True,
    )
    path = ValidPath(path_id="p1", expected_actions=[req_node])
    expectation = TrajectoryExpectation(scenario_id="test-sc", valid_paths=[path])
    matcher = DeterministicBoundedMatcher(max_search_states=0)
    evaluator = TrajectoryEvaluator(matcher=matcher)
    journal = create_empty_journal()

    scorecard = evaluator.evaluate(
        scenario=create_dummy_scenario(),
        expectation=expectation,
        journal=journal,
        run_id=str(uuid.uuid4()),
    )
    assert scorecard.overall_pass is False
    assert scorecard.evaluator_error == "evaluator_complexity_limit"


def test_json_null_differs_from_missing():
    doc = {"a": None}
    assert resolve_json_pointer(doc, "/a") is None
    assert resolve_json_pointer(doc, "/a") is not MISSING
    assert resolve_json_pointer(doc, "/b") is MISSING

    c_present = ArgumentConstraint(field_pointer="/a", operator="present")
    c_absent_null = ArgumentConstraint(field_pointer="/a", operator="absent")
    c_absent_missing = ArgumentConstraint(field_pointer="/b", operator="absent")

    assert evaluate_argument_constraint(c_present, doc) is False
    assert evaluate_argument_constraint(c_absent_null, doc) is True
    assert evaluate_argument_constraint(c_absent_missing, doc) is True


def test_numeric_range_rejects_bool_and_nan():
    c_range = ArgumentConstraint(field_pointer="/val", operator="numeric_range", value=[1, 10])
    assert evaluate_argument_constraint(c_range, {"val": True}) is False
    assert evaluate_argument_constraint(c_range, {"val": float("nan")}) is False
    assert evaluate_argument_constraint(c_range, {"val": float("inf")}) is False
    assert evaluate_argument_constraint(c_range, {"val": 5}) is True


def test_datetime_range_compares_timezones_correctly():
    c_dt = ArgumentConstraint(
        field_pointer="/ts",
        operator="datetime_range",
        value=["2026-07-28T10:00:00+00:00", "2026-07-28T12:00:00+00:00"],
    )
    assert evaluate_argument_constraint(c_dt, {"ts": "2026-07-28T13:00:00+02:00"}) is True
    assert evaluate_argument_constraint(c_dt, {"ts": "2026-07-28T09:00:00+00:00"}) is False
    assert evaluate_argument_constraint(c_dt, {"ts": "2026-07-28T11:00:00"}) is False


def test_scoring_profile_auto_normalization():
    profile = ScoringProfile(
        weight_outcome=0.5,
        weight_tool_selection=0.5,
        weight_argument_correctness=0.5,
        weight_dependency=0.5,
        weight_ordering=0.5,
        weight_efficiency=0.5,
    )
    tot = (
        profile.weight_outcome
        + profile.weight_tool_selection
        + profile.weight_argument_correctness
        + profile.weight_dependency
        + profile.weight_ordering
        + profile.weight_efficiency
    )
    assert abs(tot - 1.0) < 1e-5


def test_safety_constraints_evaluator():
    req_node = ExpectedAction(
        node_id="req1",
        selector=ActionSelector(tool_name="tool.req"),
        required=True,
    )
    path = ValidPath(path_id="p1", expected_actions=[req_node])
    expectation = TrajectoryExpectation(
        scenario_id="test-sc",
        valid_paths=[path],
        safety_constraints=[
            SafetyConstraint(rule_id="s1", constraint_type="forbidden_mutation"),
            SafetyConstraint(rule_id="s2", constraint_type="prohibited_tool"),
        ],
    )
    r_id = str(uuid.uuid4())
    c_id = uuid.uuid4()
    t0 = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    journal = HashChainJournal()
    tc = ToolCall(
        call_id=c_id,
        run_id=uuid.UUID(r_id),
        tool_name="forbidden_tool",
        arguments={},
        mutation_class="simulated_mutation",
        start_time=t0,
    )
    tr = ToolResult(call_id=c_id, status="success", result={}, end_time=t0)
    journal.append_event(
        "tool_call", run_id=r_id, correlation_id="c1", time=t0, payload=tc.model_dump(mode="json")
    )
    journal.append_event(
        "tool_result", run_id=r_id, correlation_id="c1", time=t0, payload=tr.model_dump(mode="json")
    )

    evaluator = TrajectoryEvaluator()
    scorecard = evaluator.evaluate(
        scenario=create_dummy_scenario(),
        expectation=expectation,
        journal=journal,
        run_id=r_id,
    )
    assert scorecard.safety_pass is False
    assert len(scorecard.safety_violations) == 2


def test_path_applicability_operators():
    cond_present = PathCondition(field_pointer="/token", operator="present")
    cond_absent = PathCondition(field_pointer="/error", operator="absent")
    act = ExpectedAction(node_id="n1", selector=ActionSelector(tool_name="tool.a"))
    path = ValidPath(
        path_id="p1",
        expected_actions=[act],
        applicability_conditions=[cond_present, cond_absent],
    )

    from flight_agent_evaluator.evaluation.observation import ObservedTrajectory

    obs = ObservedTrajectory(scenario_id="s", run_id="r")
    assert is_path_applicable(path, obs, initial_state={"token": "xyz"}) is True
    assert is_path_applicable(path, obs, initial_state={"token": "xyz", "error": "fatal"}) is False


def test_json_pointer_error_validation():
    with pytest.raises(ValueError, match="JSON pointer must be a string"):
        resolve_json_pointer({"a": 1}, 123)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="unescaped '~' at end"):
        resolve_json_pointer({"a~": 1}, "/a~")

    with pytest.raises(ValueError, match="Invalid array index"):
        resolve_json_pointer([1, 2, 3], "/abc")

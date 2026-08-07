"""Unit tests for Trajectory Expectation contracts and validation routines."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.contracts.trajectory_expectation import (
    ActionSelector,
    ArgumentConstraint,
    DependencyConstraint,
    ExpectedAction,
    ForbiddenActionConstraint,
    OccurrenceConstraint,
    PrecedenceConstraint,
    SafetyConstraint,
    ScoringProfile,
    TrajectoryExpectation,
    ValidPath,
    validate_trajectory_expectation,
)


def test_argument_constraint_construction():
    arg_c = ArgumentConstraint(
        field_pointer="/flight_id",
        operator="equals",
        value="AS142",
        description="Flight ID must match AS142",
    )
    assert arg_c.field_pointer == "/flight_id"
    assert arg_c.operator == "equals"
    assert arg_c.value == "AS142"


def test_strict_contract_forbids_extra_fields():
    with pytest.raises(ValidationError):
        ArgumentConstraint(
            field_pointer="/flight_id",
            operator="equals",
            value="AS142",
            extra_unknown_field="not_allowed",  # type: ignore[call-arg]
        )


def test_valid_path_graph_validation_pass():
    node_a = ExpectedAction(
        node_id="lookup_status",
        selector=ActionSelector(tool_name="flight.get_status"),
        occurrence=OccurrenceConstraint(min_occurs=1, max_occurs=1),
        required=True,
    )
    node_b = ExpectedAction(
        node_id="search_alternatives",
        selector=ActionSelector(tool_name="flight.search_flights"),
        occurrence=OccurrenceConstraint(min_occurs=1, max_occurs=2),
        required=True,
    )
    path = ValidPath(
        path_id="path_standard",
        name="Standard Investigation",
        expected_actions=[node_a, node_b],
        precedence_constraints=[
            PrecedenceConstraint(
                before_node_id="lookup_status", after_node_id="search_alternatives"
            )
        ],
        dependency_constraints=[
            DependencyConstraint(
                dependent_node_id="search_alternatives", required_node_id="lookup_status"
            )
        ],
    )
    expectation = TrajectoryExpectation(
        scenario_id="jfk-lhr-delay",
        valid_paths=[path],
    )
    assert validate_trajectory_expectation(expectation) == []


def test_valid_path_unknown_node_reference():
    node_a = ExpectedAction(
        node_id="lookup_status",
        selector=ActionSelector(tool_name="flight.get_status"),
    )
    path = ValidPath(
        path_id="path_invalid",
        expected_actions=[node_a],
        dependency_constraints=[
            DependencyConstraint(
                dependent_node_id="lookup_status", required_node_id="non_existent_node"
            )
        ],
    )
    expectation = TrajectoryExpectation(
        scenario_id="test_sc",
        valid_paths=[path],
    )
    errors = validate_trajectory_expectation(expectation)
    assert len(errors) == 1
    assert "non_existent_node" in errors[0]


def test_valid_path_cycle_detection():
    node_a = ExpectedAction(node_id="A", selector=ActionSelector(tool_name="tool_a"))
    node_b = ExpectedAction(node_id="B", selector=ActionSelector(tool_name="tool_b"))
    path = ValidPath(
        path_id="path_cycle",
        expected_actions=[node_a, node_b],
        dependency_constraints=[
            DependencyConstraint(dependent_node_id="A", required_node_id="B"),
            DependencyConstraint(dependent_node_id="B", required_node_id="A"),
        ],
    )
    expectation = TrajectoryExpectation(scenario_id="cycle_sc", valid_paths=[path])
    errors = validate_trajectory_expectation(expectation)
    assert len(errors) > 0


def test_valid_path_precedence_cycle_and_self_precedence():
    node_a = ExpectedAction(node_id="A", selector=ActionSelector(tool_name="tool_a"))
    node_b = ExpectedAction(node_id="B", selector=ActionSelector(tool_name="tool_b"))
    path = ValidPath(
        path_id="p_prec_cycle",
        expected_actions=[node_a, node_b],
        precedence_constraints=[
            PrecedenceConstraint(before_node_id="A", after_node_id="B"),
            PrecedenceConstraint(before_node_id="B", after_node_id="A"),
            PrecedenceConstraint(before_node_id="A", after_node_id="A"),
        ],
    )
    expectation = TrajectoryExpectation(scenario_id="prec_sc", valid_paths=[path])
    errors = validate_trajectory_expectation(expectation)
    assert any("self-precedence" in err for err in errors)
    assert any("precedence cycle" in err for err in errors)


def test_valid_path_duplicate_path_and_rule_ids():
    node_a = ExpectedAction(node_id="A", selector=ActionSelector(tool_name="tool_a"))
    path1 = ValidPath(
        path_id="P1",
        expected_actions=[node_a],
        forbidden_actions=[
            ForbiddenActionConstraint(rule_id="R1", selector=ActionSelector(tool_name="bad_tool")),
            ForbiddenActionConstraint(
                rule_id="R1", selector=ActionSelector(tool_name="bad_tool_2")
            ),
        ],
    )
    path2 = ValidPath(path_id="P1", expected_actions=[node_a])
    expectation = TrajectoryExpectation(
        scenario_id="dup_path_sc",
        valid_paths=[path1, path2],
        safety_constraints=[
            SafetyConstraint(rule_id="S1", constraint_type="forbidden_mutation"),
            SafetyConstraint(rule_id="S1", constraint_type="prohibited_tool"),
        ],
    )
    errors = validate_trajectory_expectation(expectation)
    assert any("duplicate path IDs" in err for err in errors)
    assert any("duplicate safety rule IDs" in err for err in errors)
    assert any("duplicate forbidden rule IDs" in err for err in errors)


def test_contradictory_required_and_forbidden_action():
    node_a = ExpectedAction(
        node_id="A", required=True, selector=ActionSelector(tool_name="flight.mutate")
    )
    path = ValidPath(
        path_id="p_contra",
        expected_actions=[node_a],
        forbidden_actions=[
            ForbiddenActionConstraint(
                rule_id="F1", selector=ActionSelector(tool_name="flight.mutate")
            )
        ],
    )
    expectation = TrajectoryExpectation(scenario_id="contra_sc", valid_paths=[path])
    errors = validate_trajectory_expectation(expectation)
    assert any("unconditionally forbidden" in err for err in errors)


def test_scoring_profile_auto_normalization():
    profile = ScoringProfile(
        weight_outcome=0.6,
        weight_tool_selection=0.4,
        weight_argument_correctness=0.4,
        weight_dependency=0.2,
        weight_ordering=0.2,
        weight_efficiency=0.2,
    )
    total = (
        profile.weight_outcome
        + profile.weight_tool_selection
        + profile.weight_argument_correctness
        + profile.weight_dependency
        + profile.weight_ordering
        + profile.weight_efficiency
    )
    assert abs(total - 1.0) < 1e-5

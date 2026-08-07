"""Unit tests for Trajectory Expectation contracts and validation routines."""

from __future__ import annotations

from flight_agent_evaluator.contracts.trajectory_expectation import (
    ActionSelector,
    ArgumentConstraint,
    DependencyConstraint,
    ExpectedAction,
    OccurrenceConstraint,
    PrecedenceConstraint,
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


def test_valid_path_precedence_unknown_node():
    node_a = ExpectedAction(node_id="A", selector=ActionSelector(tool_name="tool_a"))
    path = ValidPath(
        path_id="p_unk",
        expected_actions=[node_a],
        precedence_constraints=[
            PrecedenceConstraint(before_node_id="A", after_node_id="UNK_NODE"),
            PrecedenceConstraint(before_node_id="UNK_NODE", after_node_id="A"),
        ],
    )
    expectation = TrajectoryExpectation(scenario_id="unk_sc", valid_paths=[path])
    errors = validate_trajectory_expectation(expectation)
    assert len(errors) == 2


def test_valid_path_duplicate_node_id():
    node_a1 = ExpectedAction(node_id="A", selector=ActionSelector(tool_name="tool_a"))
    node_a2 = ExpectedAction(node_id="A", selector=ActionSelector(tool_name="tool_a"))
    path = ValidPath(path_id="p_dup", expected_actions=[node_a1, node_a2])
    expectation = TrajectoryExpectation(scenario_id="dup_sc", valid_paths=[path])
    errors = validate_trajectory_expectation(expectation)
    assert len(errors) == 1
    assert "duplicate expected node IDs" in errors[0]

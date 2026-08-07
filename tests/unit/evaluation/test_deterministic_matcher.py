"""Unit tests for Deterministic Bounded Matcher and argument predicate evaluation."""

from __future__ import annotations

from flight_agent_evaluator.contracts.trajectory_expectation import (
    ActionSelector,
    ArgumentConstraint,
    DependencyConstraint,
    ExpectedAction,
    OccurrenceConstraint,
    PrecedenceConstraint,
    ValidPath,
)
from flight_agent_evaluator.evaluation.matcher import (
    DeterministicBoundedMatcher,
    evaluate_argument_constraint,
    resolve_json_pointer,
)
from flight_agent_evaluator.evaluation.observation import ObservedToolAction, ObservedTrajectory


def test_resolve_json_pointer():
    data = {"flight_id": "AS142", "passengers": [{"name": "Alice"}, {"name": "Bob"}]}
    assert resolve_json_pointer(data, "/flight_id") == "AS142"
    assert resolve_json_pointer(data, "/passengers/0/name") == "Alice"
    assert resolve_json_pointer(data, "/passengers/1/name") == "Bob"
    assert resolve_json_pointer(data, "/non_existent") is None


def test_evaluate_argument_constraints():
    c_equals = ArgumentConstraint(field_pointer="/flight_id", operator="equals", value="AS142")
    assert evaluate_argument_constraint(c_equals, {"flight_id": "AS142"})
    assert not evaluate_argument_constraint(c_equals, {"flight_id": "AS143"})

    c_one_of = ArgumentConstraint(field_pointer="/origin", operator="one_of", value=["JFK", "EWR"])
    assert evaluate_argument_constraint(c_one_of, {"origin": "JFK"})
    assert not evaluate_argument_constraint(c_one_of, {"origin": "LAX"})

    c_range = ArgumentConstraint(field_pointer="/count", operator="numeric_range", value=[1, 5])
    assert evaluate_argument_constraint(c_range, {"count": 3})
    assert not evaluate_argument_constraint(c_range, {"count": 10})


def test_branch_and_bound_matcher_optimal_alignment():
    # Expectation: Node A (flight.get_status), Node B (flight.search_flights)
    node_a = ExpectedAction(
        node_id="A",
        selector=ActionSelector(
            tool_name="flight.get_status",
            argument_constraints=[
                ArgumentConstraint(field_pointer="/flight_id", operator="equals", value="AS142")
            ],
        ),
        occurrence=OccurrenceConstraint(min_occurs=1, max_occurs=1),
        required=True,
    )
    node_b = ExpectedAction(
        node_id="B",
        selector=ActionSelector(
            tool_name="flight.search_flights",
            argument_constraints=[
                ArgumentConstraint(field_pointer="/origin", operator="equals", value="JFK")
            ],
        ),
        occurrence=OccurrenceConstraint(min_occurs=1, max_occurs=1),
        required=True,
    )
    path = ValidPath(
        path_id="path_standard",
        expected_actions=[node_a, node_b],
        precedence_constraints=[PrecedenceConstraint(before_node_id="A", after_node_id="B")],
        dependency_constraints=[DependencyConstraint(dependent_node_id="B", required_node_id="A")],
    )

    act1 = ObservedToolAction(
        call_id="c1",
        sequence_number=1,
        tool_name="flight.get_status",
        arguments={"flight_id": "AS142"},
        mutation_class="read_only",
        start_time="2026-01-01T00:00:00Z",
    )
    act2 = ObservedToolAction(
        call_id="c2",
        sequence_number=2,
        tool_name="flight.search_flights",
        arguments={"origin": "JFK", "destination": "LHR"},
        mutation_class="read_only",
        start_time="2026-01-01T00:00:05Z",
    )

    traj = ObservedTrajectory(scenario_id="s1", run_id="r1", actions=[act1, act2])
    matcher = DeterministicBoundedMatcher()
    alignment = matcher.match(path=path, trajectory=traj)

    assert alignment.matched_node_count == 2
    assert alignment.mapping["A"].call_id == "c1"
    assert alignment.mapping["B"].call_id == "c2"
    assert alignment.precedence_satisfied
    assert alignment.dependency_satisfied


def test_greedy_vs_branch_and_bound_counterexample():
    """Prove that branch-and-bound resolves inverted order matching where greedy fails."""
    node_a = ExpectedAction(
        node_id="A",
        selector=ActionSelector(
            tool_name="flight.get_status",
            argument_constraints=[
                ArgumentConstraint(field_pointer="/flight_id", operator="equals", value="AS142")
            ],
        ),
    )
    node_b = ExpectedAction(
        node_id="B",
        selector=ActionSelector(
            tool_name="flight.get_status",
            argument_constraints=[
                ArgumentConstraint(field_pointer="/flight_id", operator="equals", value="AS143")
            ],
        ),
    )
    path = ValidPath(path_id="p_counter", expected_actions=[node_a, node_b])

    # Trajectory calls AS143 first, then AS142
    act1 = ObservedToolAction(
        call_id="c1",
        sequence_number=1,
        tool_name="flight.get_status",
        arguments={"flight_id": "AS143"},
        mutation_class="read_only",
        start_time="2026-01-01T00:00:00Z",
    )
    act2 = ObservedToolAction(
        call_id="c2",
        sequence_number=2,
        tool_name="flight.get_status",
        arguments={"flight_id": "AS142"},
        mutation_class="read_only",
        start_time="2026-01-01T00:00:05Z",
    )

    traj = ObservedTrajectory(scenario_id="s1", run_id="r1", actions=[act1, act2])
    matcher = DeterministicBoundedMatcher()
    alignment = matcher.match(path=path, trajectory=traj)

    assert alignment.matched_node_count == 2
    assert alignment.mapping["A"].call_id == "c2"
    assert alignment.mapping["B"].call_id == "c1"
    assert alignment.argument_correctness_score == 1.0


def test_all_argument_predicate_operators():
    # not_equals
    c_ne = ArgumentConstraint(field_pointer="/status", operator="not_equals", value="cancelled")
    assert evaluate_argument_constraint(c_ne, {"status": "delayed"})
    assert not evaluate_argument_constraint(c_ne, {"status": "cancelled"})

    # present / absent
    c_pres = ArgumentConstraint(field_pointer="/pnr", operator="present")
    assert evaluate_argument_constraint(c_pres, {"pnr": "PNR123"})
    assert not evaluate_argument_constraint(c_pres, {"pnr": ""})

    c_abs = ArgumentConstraint(field_pointer="/error", operator="absent")
    assert evaluate_argument_constraint(c_abs, {})
    assert not evaluate_argument_constraint(c_abs, {"error": "failed"})

    # datetime_range
    c_dt = ArgumentConstraint(
        field_pointer="/time",
        operator="datetime_range",
        value=["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
    )
    assert evaluate_argument_constraint(c_dt, {"time": "2026-01-01T12:00:00Z"})
    assert not evaluate_argument_constraint(c_dt, {"time": "2026-01-03T00:00:00Z"})

    # subset
    c_sub = ArgumentConstraint(field_pointer="/tags", operator="subset", value=["a", "b", "c"])
    assert evaluate_argument_constraint(c_sub, {"tags": ["a", "b"]})
    assert not evaluate_argument_constraint(c_sub, {"tags": ["a", "d"]})

    # canonical_equals
    c_can = ArgumentConstraint(field_pointer="/code", operator="canonical_equals", value="AS142")
    assert evaluate_argument_constraint(c_can, {"code": "AS142"})

    # reference_equals
    c_ref = ArgumentConstraint(
        field_pointer="/id", operator="reference_equals", reference_pointer="/ref_id"
    )
    prev_act = ObservedToolAction(
        call_id="c0",
        sequence_number=1,
        tool_name="flight.get_status",
        arguments={},
        result={"ref_id": "123"},
        start_time="2026-01-01T00:00:00Z",
    )
    assert evaluate_argument_constraint(c_ref, {"id": "123"}, history_actions=[prev_act])
    assert not evaluate_argument_constraint(c_ref, {"id": "456"}, history_actions=[prev_act])


def test_matcher_max_states_limit():
    # Test state limit pruning
    nodes = [
        ExpectedAction(
            node_id=f"N_{i}",
            selector=ActionSelector(tool_name="flight.get_status"),
        )
        for i in range(10)
    ]
    path = ValidPath(path_id="long_path", expected_actions=nodes)

    actions = [
        ObservedToolAction(
            call_id=f"c_{j}",
            sequence_number=j + 1,
            tool_name="flight.get_status",
            arguments={"flight_id": f"AS{j}"},
            start_time="2026-01-01T00:00:00Z",
        )
        for j in range(10)
    ]
    traj = ObservedTrajectory(scenario_id="s", run_id="r", actions=actions)

    matcher = DeterministicBoundedMatcher(max_search_states=10)
    res = matcher.match(path, traj)
    assert res.complexity_exceeded

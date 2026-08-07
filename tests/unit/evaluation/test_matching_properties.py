"""Property-based tests for matching algorithm invariants using Hypothesis."""

from __future__ import annotations

from hypothesis import given, strategies as st

from flight_agent_evaluator.contracts.trajectory_expectation import (
    ActionSelector,
    ArgumentConstraint,
    ExpectedAction,
    ValidPath,
)
from flight_agent_evaluator.evaluation.matcher import (
    DeterministicBoundedMatcher,
)
from flight_agent_evaluator.evaluation.observation import ObservedToolAction, ObservedTrajectory


@given(st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=5))
def test_matcher_injective_invariant(flight_ids: list[str]):
    """Property: Matcher mapping never assigns the same tool call_id to two expected nodes."""
    expected_actions = [
        ExpectedAction(
            node_id=f"node_{idx}",
            selector=ActionSelector(
                tool_name="flight.get_status",
                argument_constraints=[
                    ArgumentConstraint(field_pointer="/flight_id", operator="equals", value=fid)
                ],
            ),
        )
        for idx, fid in enumerate(flight_ids)
    ]
    path = ValidPath(path_id="prop_path", expected_actions=expected_actions)

    observed_actions = [
        ObservedToolAction(
            call_id=f"call_{idx}",
            sequence_number=idx + 1,
            tool_name="flight.get_status",
            arguments={"flight_id": fid},
            start_time="2026-01-01T00:00:00Z",
        )
        for idx, fid in enumerate(flight_ids)
    ]
    traj = ObservedTrajectory(scenario_id="prop_sc", run_id="r1", actions=observed_actions)

    matcher = DeterministicBoundedMatcher()
    res = matcher.match(path, traj)

    assigned_call_ids = [act.call_id for act in res.mapping.values()]
    # Invariant: unique call IDs assigned
    assert len(assigned_call_ids) == len(set(assigned_call_ids))

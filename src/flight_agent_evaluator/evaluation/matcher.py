"""Deterministic Bounded Matcher for Trajectory Constraint Graphs.

Implements non-greedy branch-and-bound optimization to compute the optimal
injective alignment between an ObservedTrajectory and a ValidPath constraint graph.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from pydantic import BaseModel, Field

from flight_agent_evaluator.contracts.trajectory_expectation import (
    ArgumentConstraint,
    ValidPath,
)
from flight_agent_evaluator.evaluation.observation import ObservedToolAction, ObservedTrajectory

# ---------------------------------------------------------------------------
# JSON Pointer & Argument Constraint Evaluator
# ---------------------------------------------------------------------------


def resolve_json_pointer(data: dict[str, Any] | list[Any], pointer: str) -> Any:
    """Resolve a JSON Pointer string (RFC 6901) against a nested dict/list data structure."""
    if not pointer or pointer == "/":
        return data

    parts = pointer.lstrip("/").split("/")
    curr: Any = data

    for part in parts:
        part_unescaped = part.replace("~1", "/").replace("~0", "~")
        if isinstance(curr, dict):
            if part_unescaped not in curr:
                return None
            curr = curr[part_unescaped]
        elif isinstance(curr, list):
            try:
                idx = int(part_unescaped)
                if idx < 0 or idx >= len(curr):
                    return None
                curr = curr[idx]
            except ValueError:
                return None
        else:
            return None

    return curr


def evaluate_argument_constraint(
    constraint: ArgumentConstraint,
    arguments: dict[str, Any],
    history_actions: list[ObservedToolAction] | None = None,
) -> bool:
    """Evaluate a single ArgumentConstraint predicate against tool arguments."""
    actual = resolve_json_pointer(arguments, constraint.field_pointer)
    op = constraint.operator
    expected = constraint.value

    if op == "equals":
        return bool(actual == expected)
    if op == "not_equals":
        return bool(actual != expected)
    if op == "one_of":
        if isinstance(expected, (list, set, tuple)):
            return actual in expected
        return False
    if op == "present":
        return actual is not None and actual != ""
    if op == "absent":
        return actual is None or actual == ""
    if op == "numeric_range":
        if (
            isinstance(actual, (int, float))
            and isinstance(expected, (list, tuple))
            and len(expected) == 2
        ):
            return bool(expected[0] <= actual <= expected[1])
        return False
    if op == "datetime_range":
        if isinstance(actual, str) and isinstance(expected, (list, tuple)) and len(expected) == 2:
            return bool(expected[0] <= actual <= expected[1])
        return False
    if op == "subset":
        if isinstance(actual, (list, set, tuple)) and isinstance(expected, (list, set, tuple)):
            return set(actual).issubset(set(expected))
        return False
    if op == "canonical_equals":
        return str(actual).strip().lower() == str(expected).strip().lower()
    if op == "reference_equals":
        if constraint.reference_pointer and history_actions:
            for act in reversed(history_actions):
                if act.result:
                    ref_val = resolve_json_pointer(act.result, constraint.reference_pointer)
                    if ref_val is not None and ref_val == actual:
                        return True
        return False

    return False


# ---------------------------------------------------------------------------
# Alignment Output Data Models
# ---------------------------------------------------------------------------


class PathAlignmentResult(BaseModel):
    """Result of aligning an ObservedTrajectory against a ValidPath."""

    path_id: str = Field(..., description="Target path identifier.")
    matched_node_count: int = Field(default=0, description="Count of expected nodes matched.")
    mapping: dict[str, ObservedToolAction] = Field(
        default_factory=dict, description="Map of node_id -> matched ObservedToolAction."
    )
    unmatched_node_ids: list[str] = Field(
        default_factory=list, description="Expected required node IDs not matched."
    )
    unmatched_action_call_ids: list[str] = Field(
        default_factory=list, description="Observed tool call IDs not matched to any node."
    )
    argument_correctness_score: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Passed argument predicates / total evaluated."
    )
    precedence_satisfied: bool = Field(
        default=True, description="True if all precedence constraints passed."
    )
    dependency_satisfied: bool = Field(
        default=True, description="True if all dependency constraints passed."
    )
    precedence_violations: list[str] = Field(
        default_factory=list, description="Descriptions of violated ordering rules."
    )
    dependency_violations: list[str] = Field(
        default_factory=list, description="Descriptions of missing dependency nodes."
    )
    complexity_exceeded: bool = Field(
        default=False, description="True if branch-and-bound search state limit was hit."
    )


# ---------------------------------------------------------------------------
# Deterministic Bounded Matcher Implementation
# ---------------------------------------------------------------------------


class DeterministicBoundedMatcher:
    """Non-greedy branch-and-bound matcher for constraint graphs."""

    def __init__(self, max_search_states: int = 10000, max_candidates_per_node: int = 10) -> None:
        self.max_search_states = max_search_states
        self.max_candidates_per_node = max_candidates_per_node

    def match(self, path: ValidPath, trajectory: ObservedTrajectory) -> PathAlignmentResult:
        """Find optimal injective alignment between ValidPath graph and ObservedTrajectory."""
        expected_nodes = path.expected_actions
        observed_actions = trajectory.actions

        # Step 1: Find candidate observed actions per node
        candidates_per_node: dict[str, list[ObservedToolAction]] = {}
        for node in expected_nodes:
            cands: list[ObservedToolAction] = []
            sel = node.selector
            for act in observed_actions:
                # Name match (exact or glob)
                if sel.tool_name and not fnmatch.fnmatch(act.tool_name, sel.tool_name):
                    continue
                # Mutation class match
                if sel.mutation_class and act.mutation_class != sel.mutation_class:
                    continue
                cands.append(act)

            # Cap candidates per node
            candidates_per_node[node.node_id] = cands[: self.max_candidates_per_node]

        # Step 2: Branch-and-bound search for optimal injective mapping
        best_mapping: dict[str, ObservedToolAction] = {}
        best_score = -1.0
        states_explored = 0
        complexity_exceeded = False

        node_list = list(expected_nodes)

        def compute_mapping_score(current_map: dict[str, ObservedToolAction]) -> float:
            score = 0.0
            total_args_evaluated = 0
            passed_args = 0

            for node in expected_nodes:
                if node.node_id in current_map:
                    act = current_map[node.node_id]
                    # Required node matched bonus
                    if node.required:
                        score += 10.0
                    else:
                        score += 2.0

                    # Argument correctness evaluation
                    for arg_c in node.selector.argument_constraints:
                        total_args_evaluated += 1
                        if evaluate_argument_constraint(arg_c, act.arguments):
                            passed_args += 1
                            score += 5.0
                        else:
                            score -= 2.0

            # Precedence ordering check bonus/penalty
            for prec in path.precedence_constraints:
                if prec.before_node_id in current_map and prec.after_node_id in current_map:
                    seq_before = current_map[prec.before_node_id].sequence_number
                    seq_after = current_map[prec.after_node_id].sequence_number
                    if seq_before < seq_after:
                        score += 3.0
                    else:
                        score -= 5.0

            return score

        def search(
            node_idx: int,
            current_map: dict[str, ObservedToolAction],
            used_call_ids: set[str],
        ) -> None:
            nonlocal best_mapping, best_score, states_explored, complexity_exceeded

            states_explored += 1
            if states_explored > self.max_search_states:
                complexity_exceeded = True
                return

            if node_idx == len(node_list):
                sc = compute_mapping_score(current_map)
                if sc > best_score:
                    best_score = sc
                    best_mapping = dict(current_map)
                return

            node = node_list[node_idx]
            node_id = node.node_id
            cands = candidates_per_node[node_id]

            # Option A: Match node to a candidate observed action
            for cand in cands:
                if cand.call_id not in used_call_ids:
                    current_map[node_id] = cand
                    used_call_ids.add(cand.call_id)

                    search(node_idx + 1, current_map, used_call_ids)

                    used_call_ids.remove(cand.call_id)
                    del current_map[node_id]

            # Option B: Leave node unmatched (if optional or if no valid candidate)
            search(node_idx + 1, current_map, used_call_ids)

        search(0, {}, set())

        # Step 3: Evaluate final metrics on best mapping
        matched_call_ids = {act.call_id for act in best_mapping.values()}
        unmatched_call_ids = [
            act.call_id for act in observed_actions if act.call_id not in matched_call_ids
        ]
        unmatched_node_ids = [
            n.node_id for n in expected_nodes if n.required and n.node_id not in best_mapping
        ]

        total_args = 0
        passed_args = 0
        for node in expected_nodes:
            if node.node_id in best_mapping:
                act = best_mapping[node.node_id]
                for arg_c in node.selector.argument_constraints:
                    total_args += 1
                    if evaluate_argument_constraint(arg_c, act.arguments):
                        passed_args += 1

        arg_correctness = (passed_args / total_args) if total_args > 0 else 1.0

        # Check precedence rules
        precedence_satisfied = True
        prec_violations: list[str] = []
        for prec in path.precedence_constraints:
            if prec.before_node_id in best_mapping and prec.after_node_id in best_mapping:
                seq_before = best_mapping[prec.before_node_id].sequence_number
                seq_after = best_mapping[prec.after_node_id].sequence_number
                if seq_before >= seq_after:
                    precedence_satisfied = False
                    prec_violations.append(
                        f"Precedence violation: Node '{prec.before_node_id}' (seq {seq_before}) did not precede '{prec.after_node_id}' (seq {seq_after})."
                    )

        # Check dependency rules
        dependency_satisfied = True
        dep_violations: list[str] = []
        for dep in path.dependency_constraints:
            if dep.dependent_node_id in best_mapping and dep.required_node_id not in best_mapping:
                dependency_satisfied = False
                dep_violations.append(
                    f"Dependency violation: Node '{dep.dependent_node_id}' executed without required node '{dep.required_node_id}'."
                )

        return PathAlignmentResult(
            path_id=path.path_id,
            matched_node_count=len(best_mapping),
            mapping=best_mapping,
            unmatched_node_ids=unmatched_node_ids,
            unmatched_action_call_ids=unmatched_call_ids,
            argument_correctness_score=arg_correctness,
            precedence_satisfied=precedence_satisfied,
            dependency_satisfied=dependency_satisfied,
            precedence_violations=prec_violations,
            dependency_violations=dep_violations,
            complexity_exceeded=complexity_exceeded,
        )

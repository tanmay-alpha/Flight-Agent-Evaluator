"""Deterministic Bounded Matcher for Trajectory Constraint Graphs.

Implements optimal injective alignment between an ObservedTrajectory and a
ValidPath constraint graph under alignment objective 'trajectory-alignment-v1'.
"""

from __future__ import annotations

import fnmatch
import math
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from flight_agent_evaluator.canonical import canonical_json
from flight_agent_evaluator.contracts.json_pointer import MISSING, resolve_json_pointer
from flight_agent_evaluator.contracts.trajectory_expectation import (
    ArgumentConstraint,
    ValidPath,
)
from flight_agent_evaluator.evaluation.observation import ObservedToolAction, ObservedTrajectory

ALIGNMENT_OBJECTIVE_VERSION = "trajectory-alignment-v1"

# ---------------------------------------------------------------------------
# Argument Predicate Engine
# ---------------------------------------------------------------------------


def _parse_utc_datetime(val: Any) -> datetime | None:
    """Parse *val* into a timezone-aware UTC datetime.

    Returns None if parsing fails or timestamp is naive.
    """
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return None
        return val.astimezone(UTC)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return None
            return dt.astimezone(UTC)
        except (ValueError, TypeError):
            return None
    return None


def evaluate_argument_constraint(
    constraint: ArgumentConstraint,
    arguments: dict[str, Any],
    aligned_mapping: dict[str, ObservedToolAction] | None = None,
) -> bool:
    """Evaluate a single ArgumentConstraint predicate against tool arguments."""
    actual = resolve_json_pointer(arguments, constraint.field_pointer)
    op = constraint.operator
    expected = constraint.value

    if op == "equals":
        if actual is MISSING:
            return False
        return bool(actual == expected)

    if op == "not_equals":
        if actual is MISSING:
            return False
        return bool(actual != expected)

    if op == "one_of":
        if actual is MISSING or not isinstance(expected, (list, set, tuple)):
            return False
        return actual in expected

    if op == "present":
        return actual is not MISSING and actual is not None and actual != ""

    if op == "absent":
        return actual is MISSING or actual is None or actual == ""

    if op == "numeric_range":
        if (
            actual is MISSING
            or isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or math.isnan(actual)
            or math.isinf(actual)
            or not isinstance(expected, (list, tuple))
            or len(expected) != 2
        ):
            return False
        return bool(expected[0] <= actual <= expected[1])

    if op == "datetime_range":
        if actual is MISSING or not isinstance(expected, (list, tuple)) or len(expected) != 2:
            return False
        actual_dt = _parse_utc_datetime(actual)
        exp_start_dt = _parse_utc_datetime(expected[0])
        exp_end_dt = _parse_utc_datetime(expected[1])
        if actual_dt is None or exp_start_dt is None or exp_end_dt is None:
            return False
        return bool(exp_start_dt <= actual_dt <= exp_end_dt)

    if op == "subset":
        # Explicit semantics: expected ⊆ actual (actual contains all expected elements)
        if (
            actual is MISSING
            or not isinstance(actual, (list, set, tuple))
            or not isinstance(expected, (list, set, tuple))
        ):
            return False
        return set(expected).issubset(set(actual))

    if op == "canonical_equals":
        if actual is MISSING:
            return False
        try:
            return canonical_json(actual) == canonical_json(expected)
        except Exception:
            return str(actual).strip() == str(expected).strip()

    if op == "reference_equals":
        if actual is MISSING:
            return False
        ref_node_id = constraint.reference_node_id
        ref_pointer = constraint.reference_field_pointer
        if ref_node_id and ref_pointer and aligned_mapping and ref_node_id in aligned_mapping:
            target_action = aligned_mapping[ref_node_id]
            if target_action.result:
                ref_val = resolve_json_pointer(target_action.result, ref_pointer)
                if ref_val is not MISSING and ref_val == actual:
                    return True
        return False

    return False


# ---------------------------------------------------------------------------
# Alignment Output Data Models
# ---------------------------------------------------------------------------


def _qualifies_result_status(expected_status: str, act: ObservedToolAction) -> bool:
    """Evaluate whether an observed tool action satisfies the expected result status."""
    if expected_status == "success":
        return act.is_successful
    if expected_status == "error":
        return not act.is_successful
    return True  # "any"


# ---------------------------------------------------------------------------
# Alignment Output Data Models
# ---------------------------------------------------------------------------


class PathAlignmentResult(BaseModel):
    """Result of aligning an ObservedTrajectory against a ValidPath."""

    path_id: str = Field(..., description="Target path identifier.")
    matched_node_count: int = Field(default=0, description="Count of expected nodes satisfied.")
    satisfied_node_ids: list[str] = Field(
        default_factory=list, description="Node IDs successfully satisfied."
    )
    mapping: dict[str, ObservedToolAction] = Field(
        default_factory=dict, description="Map of node_id -> primary matched ObservedToolAction."
    )
    node_actions: dict[str, list[ObservedToolAction]] = Field(
        default_factory=dict, description="Map of node_id -> all qualifying matching actions."
    )
    unmatched_node_ids: list[str] = Field(
        default_factory=list, description="Expected required node IDs not satisfied."
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
    occurrence_satisfied: bool = Field(
        default=True, description="True if all occurrence constraints were met."
    )
    precedence_violations: list[str] = Field(
        default_factory=list, description="Descriptions of violated ordering rules."
    )
    dependency_violations: list[str] = Field(
        default_factory=list, description="Descriptions of missing dependency nodes."
    )
    occurrence_violations: list[str] = Field(
        default_factory=list, description="Descriptions of violated occurrence bounds."
    )
    result_status_violations: list[str] = Field(
        default_factory=list, description="Descriptions of failed/unexpected result statuses."
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

        # Step 1: Candidate set generation per node
        candidates_per_node: dict[str, list[ObservedToolAction]] = {}
        for node in expected_nodes:
            cands: list[ObservedToolAction] = []
            sel = node.selector
            for act in observed_actions:
                if sel.tool_name and not fnmatch.fnmatch(act.tool_name, sel.tool_name):
                    continue
                if sel.mutation_class and act.mutation_class != sel.mutation_class:
                    continue
                cands.append(act)

            candidates_per_node[node.node_id] = cands[: self.max_candidates_per_node]

        # Step 2: Branch-and-bound search for optimal injective alignment under trajectory-alignment-v1
        best_mapping: dict[str, ObservedToolAction] = {}
        best_objective: tuple[int, ...] = (-1, -1, -1, -1, -1, -999999, -999999)
        states_explored = 0
        complexity_exceeded = False

        node_list = list(expected_nodes)

        def compute_objective_tuple(current_map: dict[str, ObservedToolAction]) -> tuple[int, ...]:
            satisfied_req = 0
            satisfied_opt = 0
            passed_args = 0

            for n in expected_nodes:
                if n.node_id in current_map:
                    act = current_map[n.node_id]
                    res_ok = _qualifies_result_status(n.expected_result_status, act)
                    args_ok = True
                    for arg_c in n.selector.argument_constraints:
                        if evaluate_argument_constraint(
                            arg_c, act.arguments, aligned_mapping=current_map
                        ):
                            passed_args += 1
                        else:
                            args_ok = False

                    if res_ok and args_ok:
                        if n.required:
                            satisfied_req += 1
                        else:
                            satisfied_opt += 1

            satisfied_deps = 0
            for dep in path.dependency_constraints:
                if dep.dependent_node_id in current_map and dep.required_node_id in current_map:
                    req_act = current_map[dep.required_node_id]
                    req_node = next(
                        (node for node in expected_nodes if node.node_id == dep.required_node_id),
                        None,
                    )
                    if req_node and _qualifies_result_status(
                        req_node.expected_result_status, req_act
                    ):
                        satisfied_deps += 1

            satisfied_precs = 0
            for prec in path.precedence_constraints:
                if (
                    prec.before_node_id in current_map
                    and prec.after_node_id in current_map
                    and current_map[prec.before_node_id].sequence_number
                    < current_map[prec.after_node_id].sequence_number
                ):
                    satisfied_precs += 1

            unmatched_calls = len(observed_actions) - len(current_map)
            seq_sum = sum(act.sequence_number for act in current_map.values())

            return (
                satisfied_req,
                passed_args,
                satisfied_deps,
                satisfied_precs,
                satisfied_opt,
                -unmatched_calls,
                -seq_sum,
            )

        def search(
            node_idx: int,
            current_map: dict[str, ObservedToolAction],
            used_call_ids: set[str],
        ) -> None:
            nonlocal best_mapping, best_objective, states_explored, complexity_exceeded

            states_explored += 1
            if states_explored > self.max_search_states:
                complexity_exceeded = True
                return

            if node_idx == len(node_list):
                obj = compute_objective_tuple(current_map)
                if obj > best_objective:
                    best_objective = obj
                    best_mapping = dict(current_map)
                return

            node = node_list[node_idx]
            node_id = node.node_id
            cands = candidates_per_node[node_id]

            for cand in cands:
                if cand.call_id not in used_call_ids:
                    current_map[node_id] = cand
                    used_call_ids.add(cand.call_id)

                    search(node_idx + 1, current_map, used_call_ids)

                    used_call_ids.remove(cand.call_id)
                    del current_map[node_id]

            search(node_idx + 1, current_map, used_call_ids)

        search(0, {}, set())

        # Step 3: Evaluate final metrics on best mapping
        matched_call_ids = {act.call_id for act in best_mapping.values()}
        unmatched_call_ids = [
            act.call_id for act in observed_actions if act.call_id not in matched_call_ids
        ]

        total_args = 0
        passed_args = 0
        node_actions: dict[str, list[ObservedToolAction]] = {}
        satisfied_node_ids: list[str] = []
        result_status_violations: list[str] = []
        occurrence_violations: list[str] = []
        occurrence_satisfied = True

        for node in expected_nodes:
            # Find all matching qualifying actions for occurrence checking
            matching_calls: list[ObservedToolAction] = []
            for act in observed_actions:
                if node.selector.tool_name and not fnmatch.fnmatch(
                    act.tool_name, node.selector.tool_name
                ):
                    continue
                if (
                    node.selector.mutation_class
                    and act.mutation_class != node.selector.mutation_class
                ):
                    continue
                # Check arguments
                args_valid = True
                for arg_c in node.selector.argument_constraints:
                    if not evaluate_argument_constraint(
                        arg_c, act.arguments, aligned_mapping=best_mapping
                    ):
                        args_valid = False
                        break
                if not args_valid:
                    continue
                # Check result status
                if not _qualifies_result_status(node.expected_result_status, act):
                    continue
                matching_calls.append(act)

            node_actions[node.node_id] = matching_calls
            count = len(matching_calls)
            min_o = node.occurrence.min_occurs
            max_o = node.occurrence.max_occurs

            if node.node_id in best_mapping:
                act = best_mapping[node.node_id]
                res_ok = _qualifies_result_status(node.expected_result_status, act)
                if not res_ok:
                    result_status_violations.append(
                        f"Result status violation: Node '{node.node_id}' expected status '{node.expected_result_status}', "
                        f"but tool call '{act.tool_name}' (call_id {act.call_id}) had status '{act.status}'."
                    )

                node_args_passed = True
                for arg_c in node.selector.argument_constraints:
                    total_args += 1
                    if evaluate_argument_constraint(
                        arg_c, act.arguments, aligned_mapping=best_mapping
                    ):
                        passed_args += 1
                    else:
                        node_args_passed = False

                # Occurrence check
                if count < min_o:
                    occurrence_satisfied = False
                    occurrence_violations.append(
                        f"Occurrence violation: Node '{node.node_id}' requires minimum {min_o} occurrences, observed {count}."
                    )
                if max_o is not None and count > max_o:
                    occurrence_satisfied = False
                    occurrence_violations.append(
                        f"Occurrence violation: Node '{node.node_id}' permits maximum {max_o} occurrences, observed {count}."
                    )

                if (
                    res_ok
                    and node_args_passed
                    and min_o <= count <= (max_o if max_o is not None else 999999)
                ):
                    satisfied_node_ids.append(node.node_id)
            else:
                if node.required and min_o > 0:
                    occurrence_satisfied = False
                    occurrence_violations.append(
                        f"Occurrence violation: Required node '{node.node_id}' was not observed (requires min {min_o})."
                    )

        unmatched_node_ids = [
            n.node_id for n in expected_nodes if n.required and n.node_id not in satisfied_node_ids
        ]

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
            elif prec.after_node_id in best_mapping and prec.before_node_id not in best_mapping:
                before_node = next(
                    (n for n in expected_nodes if n.node_id == prec.before_node_id), None
                )
                if before_node and before_node.required:
                    precedence_satisfied = False
                    prec_violations.append(
                        f"Precedence violation: Node '{prec.after_node_id}' executed without prior execution of required predecessor '{prec.before_node_id}'."
                    )

        # Check dependency rules
        dependency_satisfied = True
        dep_violations: list[str] = []
        for dep in path.dependency_constraints:
            if (
                dep.dependent_node_id in best_mapping
                and dep.required_node_id not in satisfied_node_ids
            ):
                dependency_satisfied = False
                dep_violations.append(
                    f"Dependency violation: node '{dep.dependent_node_id}' depends on required node '{dep.required_node_id}', "
                    f"which was not successfully satisfied."
                )

        return PathAlignmentResult(
            path_id=path.path_id,
            matched_node_count=len(satisfied_node_ids),
            satisfied_node_ids=satisfied_node_ids,
            mapping=best_mapping,
            node_actions=node_actions,
            unmatched_node_ids=unmatched_node_ids,
            unmatched_action_call_ids=unmatched_call_ids,
            argument_correctness_score=arg_correctness,
            precedence_satisfied=precedence_satisfied,
            dependency_satisfied=dependency_satisfied,
            occurrence_satisfied=occurrence_satisfied,
            precedence_violations=prec_violations,
            dependency_violations=dep_violations,
            occurrence_violations=occurrence_violations,
            result_status_violations=result_status_violations,
            complexity_exceeded=complexity_exceeded,
        )

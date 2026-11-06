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
    DependencyConstraint,
    ExpectedAction,
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
    *,
    dependent_action: ObservedToolAction | None = None,
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
            or (isinstance(actual, float) and not math.isfinite(actual))
            or not isinstance(expected, (list, tuple))
            or len(expected) != 2
            or any(
                isinstance(bound, bool)
                or not isinstance(bound, (int, float))
                or (isinstance(bound, float) and not math.isfinite(bound))
                for bound in expected
            )
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
        if (
            ref_node_id is not None
            and ref_pointer is not None
            and aligned_mapping
            and ref_node_id in aligned_mapping
            and dependent_action is not None
        ):
            target_action = aligned_mapping[ref_node_id]
            if _is_prior_success(target_action, dependent_action) and target_action.result is not None:
                ref_val = resolve_json_pointer(target_action.result, ref_pointer)
                return ref_val is not MISSING and ref_val == actual
        return False

    return False


def _is_prior_success(required: ObservedToolAction, dependent: ObservedToolAction) -> bool:
    """A dependency consumes a completed result, not a future or failed call."""
    return (
        required.is_successful
        and required.sequence_number < dependent.sequence_number
        and (
            required.result_journal_sequence is None
            or dependent.journal_sequence is None
            or required.result_journal_sequence < dependent.journal_sequence
        )
    )


def _dependency_holds(
    dependency: DependencyConstraint, mapping: dict[str, ObservedToolAction]
) -> bool:
    required = mapping.get(dependency.required_node_id)
    dependent = mapping.get(dependency.dependent_node_id)
    if required is None or dependent is None or not _is_prior_success(required, dependent):
        return False
    for binding in dependency.bindings:
        actual = resolve_json_pointer(dependent.arguments, binding.argument_pointer)
        expected = resolve_json_pointer(required.result, binding.result_pointer)
        if actual is MISSING or expected is MISSING or actual != expected:
            return False
    return True


def _node_qualifies(
    node: ExpectedAction, action: ObservedToolAction, mapping: dict[str, ObservedToolAction]
) -> bool:
    return _qualifies_result_status(node.expected_result_status, action) and all(
        evaluate_argument_constraint(
            constraint, action.arguments, mapping, dependent_action=action
        )
        for constraint in node.selector.argument_constraints
    )


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
        default_factory=dict, description="Exclusively assigned occurrences, including allowed retry attempts."
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
    """Deterministic branch-and-bound matcher for constraint graphs.

    Candidates for a node are filtered by tool name and mutation class, then ranked
    so that locally qualifying calls (result status and non-reference argument
    predicates hold) come first, in journal order; only then is the per-node
    candidate cap applied, so a correct call is never displaced by near misses.

    The depth-first search prunes any branch whose optimistic objective bound
    cannot strictly beat the best complete alignment found so far. The bound is
    admissible (never below the true best completion), so pruning never changes
    the selected alignment; ``max_search_states`` remains a hard work budget.
    """

    def __init__(self, max_search_states: int = 10000, max_candidates_per_node: int = 10) -> None:
        self.max_search_states = max_search_states
        self.max_candidates_per_node = max_candidates_per_node

    def match(self, path: ValidPath, trajectory: ObservedTrajectory) -> PathAlignmentResult:
        """Find optimal injective alignment between ValidPath graph and ObservedTrajectory."""
        expected_nodes = path.expected_actions
        observed_actions = trajectory.actions
        node_list = list(expected_nodes)
        node_index = {node.node_id: i for i, node in enumerate(node_list)}

        # Step 1: Candidate generation with optimistic node-local scores.
        # local[(node_id, call_id)] = (qualifies, optimistic passed-argument count); reference
        # predicates depend on the final mapping and are counted optimistically as passing.
        candidates_per_node: dict[str, list[ObservedToolAction]] = {}
        local: dict[tuple[str, str], tuple[bool, int]] = {}
        for node in node_list:
            sel = node.selector
            cands: list[ObservedToolAction] = []
            for act in observed_actions:
                if sel.tool_name and not fnmatch.fnmatch(act.tool_name, sel.tool_name):
                    continue
                if sel.mutation_class and act.mutation_class != sel.mutation_class:
                    continue
                passed = 0
                args_ok = True
                for arg_c in sel.argument_constraints:
                    if arg_c.operator == "reference_equals" or evaluate_argument_constraint(
                        arg_c, act.arguments
                    ):
                        passed += 1
                    else:
                        args_ok = False
                qualifies = args_ok and _qualifies_result_status(node.expected_result_status, act)
                local[(node.node_id, act.call_id)] = (qualifies, passed)
                cands.append(act)
            node_local = {act.call_id: local[(node.node_id, act.call_id)][0] for act in cands}
            cands.sort(key=lambda a: (not node_local[a.call_id], a.sequence_number))
            candidates_per_node[node.node_id] = cands[: self.max_candidates_per_node]

        # Optimistic contributions of a node that is not decided yet.
        max_req = [0] * len(node_list)
        max_opt = [0] * len(node_list)
        max_args = [0] * len(node_list)
        min_seq: list[int | None] = [None] * len(node_list)
        for i, node in enumerate(node_list):
            cands = candidates_per_node[node.node_id]
            if not cands:
                continue
            any_ok = any(local[(node.node_id, c.call_id)][0] for c in cands)
            if node.required:
                max_req[i] = int(any_ok)
            else:
                max_opt[i] = int(any_ok)
            max_args[i] = max(local[(node.node_id, c.call_id)][1] for c in cands)
            min_seq[i] = min(c.sequence_number for c in cands)

        # Step 2: Branch-and-bound search for optimal injective alignment under trajectory-alignment-v1
        best_mapping: dict[str, ObservedToolAction] = {}
        best_objective: tuple[int, ...] = (-1, -1, -1, -1, -1, -999999, -999999)
        states_explored = 0
        complexity_exceeded = False

        def decided_unmapped(node_id: str, node_idx: int, current_map: dict[str, Any]) -> bool:
            idx = node_index.get(node_id)
            return idx is None or (idx < node_idx and node_id not in current_map)

        def upper_bound(
            node_idx: int, current_map: dict[str, ObservedToolAction]
        ) -> tuple[int, ...]:
            req = opt = args = seq_sum = 0
            for i, node in enumerate(node_list):
                if i >= node_idx:
                    req += max_req[i]
                    opt += max_opt[i]
                    args += max_args[i]
                    continue
                act = current_map.get(node.node_id)
                if act is None:
                    continue
                qualifies, passed = local[(node.node_id, act.call_id)]
                args += passed
                seq_sum += act.sequence_number
                if qualifies:
                    if node.required:
                        req += 1
                    else:
                        opt += 1
            deps = 0
            for dep in path.dependency_constraints:
                if decided_unmapped(
                    dep.dependent_node_id, node_idx, current_map
                ) or decided_unmapped(dep.required_node_id, node_idx, current_map):
                    continue
                req_act = current_map.get(dep.required_node_id)
                req_node = node_list[node_index[dep.required_node_id]]
                if req_act is not None and not _qualifies_result_status(
                    req_node.expected_result_status, req_act
                ):
                    continue
                deps += 1
            precs = 0
            for prec in path.precedence_constraints:
                if decided_unmapped(prec.before_node_id, node_idx, current_map) or decided_unmapped(
                    prec.after_node_id, node_idx, current_map
                ):
                    continue
                before = current_map.get(prec.before_node_id)
                after = current_map.get(prec.after_node_id)
                if (
                    before is not None
                    and after is not None
                    and before.sequence_number >= after.sequence_number
                ):
                    continue
                precs += 1
            # Completions that tie on every earlier component must map as many nodes as
            # possible; each extra mapping adds at least its node's smallest sequence number.
            pending = sorted(s for s in min_seq[node_idx:] if s is not None)
            extra = min(len(pending), max(0, len(observed_actions) - len(current_map)))
            unmatched = len(observed_actions) - len(current_map) - extra
            seq_sum += sum(pending[:extra])
            return (req, args, deps, precs, opt, -unmatched, -seq_sum)

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
                            arg_c, act.arguments, aligned_mapping=current_map, dependent_action=act
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
                if _dependency_holds(dep, current_map):
                    req_node = node_list[node_index[dep.required_node_id]]
                    if _node_qualifies(req_node, current_map[dep.required_node_id], current_map):
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

            if complexity_exceeded:
                return
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

            if upper_bound(node_idx, current_map) <= best_objective:
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

        # Assign each qualifying call to exactly one node. Primary anchors remain
        # injective; additional occurrences fill minima then available capacity,
        # with nearest-anchor sequence and node id as deterministic tie-breaks.
        node_actions: dict[str, list[ObservedToolAction]] = {
            node.node_id: [] for node in expected_nodes
        }
        primary_ids = {act.call_id for act in best_mapping.values()}
        for node in expected_nodes:
            primary = best_mapping.get(node.node_id)
            if primary is not None and _node_qualifies(node, primary, best_mapping):
                node_actions[node.node_id].append(primary)
        for act in observed_actions:
            if act.call_id in primary_ids:
                continue
            eligible = [
                node for node in expected_nodes
                if node.node_id in best_mapping
                and (not node.selector.tool_name or fnmatch.fnmatch(act.tool_name, node.selector.tool_name))
                and (not node.selector.mutation_class or act.mutation_class == node.selector.mutation_class)
                and (
                    _node_qualifies(node, act, best_mapping)
                    or (
                        node.expected_result_status == "success"
                        and _node_qualifies(node, best_mapping[node.node_id], best_mapping)
                        and all(
                            evaluate_argument_constraint(
                                constraint, act.arguments, best_mapping, dependent_action=act
                            )
                            for constraint in node.selector.argument_constraints
                        )
                    )
                )
            ]
            if not eligible:
                continue
            chosen = min(
                eligible,
                key=lambda node: (
                    len(node_actions[node.node_id]) >= node.occurrence.min_occurs,
                    node.occurrence.max_occurs is not None
                    and len(node_actions[node.node_id]) >= node.occurrence.max_occurs,
                    abs(act.sequence_number - best_mapping[node.node_id].sequence_number),
                    node.node_id,
                ),
            )
            node_actions[chosen.node_id].append(act)
        matched_call_ids = {
            act.call_id for actions in node_actions.values() for act in actions
        }
        unmatched_call_ids = [
            act.call_id for act in observed_actions if act.call_id not in matched_call_ids
        ]

        total_args = 0
        passed_args = 0
        # node_actions above is the exclusive occurrence assignment, not all selectors.
        satisfied_node_ids: list[str] = []
        result_status_violations: list[str] = []
        occurrence_violations: list[str] = []
        occurrence_satisfied = True

        for node in expected_nodes:
            matching_calls = node_actions[node.node_id]
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
                        arg_c, act.arguments, aligned_mapping=best_mapping, dependent_action=act
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
            if dep.dependent_node_id in best_mapping and (
                dep.required_node_id not in satisfied_node_ids
                or not _dependency_holds(dep, best_mapping)
            ):
                dependency_satisfied = False
                dep_violations.append(
                    f"Dependency violation: node '{dep.dependent_node_id}' depends on required node "
                    f"'{dep.required_node_id}': an earlier successful call with matching bound result values is required."
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

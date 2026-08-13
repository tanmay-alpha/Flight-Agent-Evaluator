"""Trajectory Evaluator Engine for multi-path constraint scoring.

Evaluates an execution trajectory against all applicable valid solution paths
in a TrajectoryExpectation, selects the winning path, and generates a composite
TrajectoryScorecard with evidence attribution.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.json_pointer import MISSING, resolve_json_pointer
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.trajectory_expectation import (
    TrajectoryExpectation,
    ValidPath,
)
from flight_agent_evaluator.engine.state import StateProjector
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.evaluation.matcher import (
    DeterministicBoundedMatcher,
    PathAlignmentResult,
    evaluate_argument_constraint,
)
from flight_agent_evaluator.evaluation.observation import (
    ObservedTrajectory,
    extract_observed_trajectory,
)
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.state import StateSnapshot

# ---------------------------------------------------------------------------
# Evidence & Attribution Models
# ---------------------------------------------------------------------------


class EvidencePointer(ContractModel):
    """Pointer referencing trusted recorded evidence in journal."""

    journal_sequence: int = Field(..., description="Journal entry sequence number.")
    entry_type: str = Field(..., description="Journal entry type (e.g. 'tool_call').")
    call_id: str | None = Field(default=None, description="Tool call ID if applicable.")
    field_pointer: str | None = Field(default=None, description="JSON pointer within payload.")
    details: str = Field(default="", description="Human-readable evidence note.")


class EvidenceAttribution(ContractModel):
    """Mapping evidence connecting expected graph node to observed journal event."""

    node_id: str = Field(..., description="Expected action node identifier.")
    matched: bool = Field(..., description="True if matched to an observed action.")
    call_id: str | None = Field(default=None, description="Matched tool call ID.")
    sequence_number: int | None = Field(default=None, description="Journal sequence number.")
    tool_name: str | None = Field(default=None, description="Tool name.")
    argument_status: str = Field(
        default="passed", description="Status of argument predicate evaluation."
    )
    details: str = Field(default="", description="Additional evidence notes.")
    pointer: EvidencePointer | None = Field(
        default=None, description="Explicit journal evidence pointer."
    )


class TrajectoryScorecard(ContractModel):
    """Multi-dimensional score vector produced by TrajectoryEvaluator."""

    scenario_id: str = Field(..., description="Scenario identifier.")
    run_id: str = Field(..., description="Run identifier.")
    selected_path_id: str = Field(..., description="Winning valid path ID.")
    overall_pass: bool = Field(
        ..., description="True if safety pass and required score thresholds met."
    )
    evaluator_error: str | None = Field(
        default=None, description="Evaluator integrity error code if evaluation failed."
    )
    outcome_score: float = Field(default=1.0, ge=0.0, le=1.0)
    tool_precision: float = Field(default=1.0, ge=0.0, le=1.0)
    required_recall: float = Field(default=1.0, ge=0.0, le=1.0)
    tool_f1: float = Field(default=1.0, ge=0.0, le=1.0)
    argument_correctness_score: float = Field(default=1.0, ge=0.0, le=1.0)
    dependency_score: float = Field(default=1.0, ge=0.0, le=1.0)
    ordering_score: float = Field(default=1.0, ge=0.0, le=1.0)
    efficiency_score: float = Field(default=1.0, ge=0.0, le=1.0)
    recovery_score: float = Field(default=1.0, ge=0.0, le=1.0)
    composite_score: float = Field(default=1.0, ge=0.0, le=1.0)
    safety_pass: bool = Field(
        default=True, description="True if zero hard safety violations occurred."
    )
    safety_violations: list[str] = Field(default_factory=list)
    evidence_attribution: list[EvidenceAttribution] = Field(default_factory=list)

    @property
    def overall_score(self) -> float:
        """Alias for composite_score."""
        return self.composite_score

    @property
    def goal_accuracy(self) -> float:
        """Alias for outcome_score."""
        return self.outcome_score

    @property
    def constraint_satisfaction(self) -> float:
        """Alias for argument_correctness_score."""
        return self.argument_correctness_score

    @property
    def unnecessary_action_count(self) -> int:
        """Count of unmatched / unnecessary actions."""
        return sum(1 for e in self.evidence_attribution if not e.matched)


# ---------------------------------------------------------------------------
# Path Applicability Evaluator
# ---------------------------------------------------------------------------


def is_path_applicable(
    path: ValidPath,
    _trajectory: ObservedTrajectory,
    initial_state: dict[str, Any] | None = None,
) -> bool:
    """Determine whether a ValidPath is applicable given current run context."""
    if not path.applicability_conditions:
        return True

    state_data = initial_state or {}

    for cond in path.applicability_conditions:
        val = resolve_json_pointer(state_data, cond.field_pointer)
        op = cond.operator
        exp = cond.value

        if op == "equals" and (val is MISSING or val != exp):
            return False
        if op == "not_equals" and (val is MISSING or val == exp):
            return False
        if op == "one_of" and (val is MISSING or val not in exp):
            return False
        if op == "present" and (val is MISSING or val is None or val == ""):
            return False
        if op == "absent" and (val is not MISSING and val is not None and val != ""):
            return False
        if op == "boolean" and (val is MISSING or bool(val) != bool(exp)):
            return False

    return True


# ---------------------------------------------------------------------------
# TrajectoryEvaluator Engine
# ---------------------------------------------------------------------------


class TrajectoryEvaluator:
    """Evaluates agent execution traces against versioned constraint graphs."""

    def __init__(self, matcher: DeterministicBoundedMatcher | None = None) -> None:
        self.matcher = matcher or DeterministicBoundedMatcher()
        self.projector = StateProjector()

    def evaluate(
        self,
        scenario: BenchmarkScenario,
        expectation: TrajectoryExpectation,
        journal: HashChainJournal,
        run_id: str,
        final_response: str | None = None,
        initial_state: dict[str, Any] | None = None,
    ) -> TrajectoryScorecard:
        """Evaluate trajectory journal against scenario expectation graph."""
        scenario_id_str = scenario.scenario_id.id
        obs_traj = extract_observed_trajectory(
            scenario_id=scenario_id_str,
            run_id=run_id,
            journal=journal,
            final_response=final_response,
        )

        # Gate 6 & 19: Reconstruct real projected final state from journal
        projected_state = StateSnapshot()
        for entry in journal.entries:
            projected_state = self.projector.project_entry(
                state=projected_state,
                entry_type=entry.type,
                payload=entry.payload,
            )

        # Gate 7: Use deterministic timestamps recorded in journal
        run_started_at = journal.entries[0].time if journal.entries else None
        run_ended_at = journal.entries[-1].time if journal.entries else None

        # Gate 16 & 17: Safety & Forbidden Action Check
        safety_violations: list[str] = []

        # Check safety rules configured in expectation
        for rule in expectation.safety_constraints:
            if rule.constraint_type == "forbidden_mutation":
                safety_violations.extend(
                    f"Safety Rule '{rule.rule_id}': Forbidden mutation action '{act.tool_name}' (call_id {act.call_id}, seq {act.sequence_number})."
                    for act in obs_traj.actions
                    if act.mutation_class != "read_only"
                )
            elif rule.constraint_type == "prohibited_tool":
                safety_violations.extend(
                    f"Safety Rule '{rule.rule_id}': Prohibited tool call '{act.tool_name}' (call_id {act.call_id})."
                    for act in obs_traj.actions
                    if act.tool_name in ("forbidden_tool", "unregistered_tool")
                )

        safety_pass = len(safety_violations) == 0

        # Step 2: Evaluate Outcome Assertions against projected state
        total_assertions = len(scenario.assertions)
        if total_assertions > 0 and run_started_at and run_ended_at:
            assertion_eval = AssertionEvaluator()
            eval_res = assertion_eval.evaluate(
                scenario=scenario,
                state=projected_state,
                journal=journal,
                replay_report=None,
                run_id=run_id,
                started_at=run_started_at,
                ended_at=run_ended_at,
            )
            outcome_pass_count = sum(1 for o in eval_res.outcomes if o.passed)
            outcome_score = outcome_pass_count / total_assertions
        else:
            outcome_score = 1.0

        # Gate 8: Find applicable paths
        applicable_paths = [
            p for p in expectation.valid_paths if is_path_applicable(p, obs_traj, initial_state)
        ]
        if not applicable_paths:
            return TrajectoryScorecard(
                scenario_id=scenario_id_str,
                run_id=run_id,
                selected_path_id="none",
                overall_pass=False,
                evaluator_error="no_applicable_path",
                outcome_score=outcome_score,
                composite_score=0.0,
                safety_pass=safety_pass,
                safety_violations=safety_violations,
            )

        path_results: list[tuple[ValidPath, PathAlignmentResult, float]] = []

        for path in applicable_paths:
            alignment = self.matcher.match(path, obs_traj)
            if alignment.complexity_exceeded:
                return TrajectoryScorecard(
                    scenario_id=scenario_id_str,
                    run_id=run_id,
                    selected_path_id=path.path_id,
                    overall_pass=False,
                    evaluator_error="evaluator_complexity_limit",
                    outcome_score=outcome_score,
                    composite_score=0.0,
                    safety_pass=safety_pass,
                    safety_violations=safety_violations,
                )

            profile = expectation.scoring_profile
            req_nodes = [n for n in path.expected_actions if n.required]

            # Gate 13: Tool selection metrics
            total_agent_calls = len(obs_traj.actions)
            matched_valid_calls = alignment.matched_node_count
            tool_precision = (
                matched_valid_calls / total_agent_calls if total_agent_calls > 0 else 1.0
            )
            required_recall = (matched_valid_calls / len(req_nodes)) if len(req_nodes) > 0 else 1.0
            if tool_precision + required_recall > 0:
                tool_f1 = (2 * tool_precision * required_recall) / (
                    tool_precision + required_recall
                )
            else:
                tool_f1 = 0.0

            # Gate 14: Proportional dependency and ordering scores
            total_deps = len(path.dependency_constraints)
            satisfied_deps = (
                total_deps - len(alignment.dependency_violations) if total_deps > 0 else 0
            )
            dep_score = (satisfied_deps / total_deps) if total_deps > 0 else 1.0

            total_precs = len(path.precedence_constraints)
            satisfied_precs = (
                total_precs - len(alignment.precedence_violations) if total_precs > 0 else 0
            )
            ord_score = (satisfied_precs / total_precs) if total_precs > 0 else 1.0

            unmatched_penalty = (
                len(alignment.unmatched_action_call_ids) * profile.unmatched_call_penalty
            )
            efficiency_score = max(0.0, 1.0 - unmatched_penalty)

            comp = (
                profile.weight_outcome * outcome_score
                + profile.weight_tool_selection * tool_f1
                + profile.weight_argument_correctness * alignment.argument_correctness_score
                + profile.weight_dependency * dep_score
                + profile.weight_ordering * ord_score
                + profile.weight_efficiency * efficiency_score
            )
            path_results.append((path, alignment, comp))

        path_results.sort(key=lambda x: (x[2], x[0].path_id), reverse=True)
        winning_path, winning_alignment, composite_score = path_results[0]

        # Gate 21: Evidence Attribution with pointers
        evidence: list[EvidenceAttribution] = []
        for node in winning_path.expected_actions:
            if node.node_id in winning_alignment.mapping:
                act = winning_alignment.mapping[node.node_id]
                args_ok = True
                for arg_c in node.selector.argument_constraints:
                    if not evaluate_argument_constraint(
                        arg_c, act.arguments, aligned_mapping=winning_alignment.mapping
                    ):
                        args_ok = False
                        break
                evidence.append(
                    EvidenceAttribution(
                        node_id=node.node_id,
                        matched=True,
                        call_id=act.call_id,
                        sequence_number=act.sequence_number,
                        tool_name=act.tool_name,
                        argument_status="passed" if args_ok else "failed",
                        details=f"Matched tool call '{act.tool_name}' (call_id {act.call_id}, seq {act.sequence_number})",
                        pointer=EvidencePointer(
                            journal_sequence=act.sequence_number,
                            entry_type="tool_call",
                            call_id=act.call_id,
                            details=f"Node '{node.node_id}' matched action '{act.tool_name}'",
                        ),
                    )
                )
            else:
                evidence.append(
                    EvidenceAttribution(
                        node_id=node.node_id,
                        matched=False,
                        argument_status="unmatched",
                        details=f"Required node '{node.node_id}' not matched in trajectory.",
                    )
                )

        # Gate 18: Strict pass semantics
        overall_pass = (
            safety_pass
            and outcome_score >= 1.0
            and winning_alignment.dependency_satisfied
            and winning_alignment.precedence_satisfied
            and len(winning_alignment.unmatched_node_ids) == 0
            and winning_alignment.argument_correctness_score >= 1.0
        )

        req_nodes_len = len([n for n in winning_path.expected_actions if n.required])
        tot_calls = len(obs_traj.actions)
        prec_val = winning_alignment.matched_node_count / tot_calls if tot_calls > 0 else 1.0
        rec_val = (
            (winning_alignment.matched_node_count / req_nodes_len) if req_nodes_len > 0 else 1.0
        )
        f1_val = (
            (2 * prec_val * rec_val / (prec_val + rec_val)) if (prec_val + rec_val) > 0 else 0.0
        )

        return TrajectoryScorecard(
            scenario_id=scenario_id_str,
            run_id=run_id,
            selected_path_id=winning_path.path_id,
            overall_pass=overall_pass,
            evaluator_error=None,
            outcome_score=outcome_score,
            tool_precision=prec_val,
            required_recall=rec_val,
            tool_f1=f1_val,
            argument_correctness_score=winning_alignment.argument_correctness_score,
            dependency_score=1.0 if winning_alignment.dependency_satisfied else 0.0,
            ordering_score=1.0 if winning_alignment.precedence_satisfied else 0.0,
            efficiency_score=max(
                0.0,
                1.0
                - len(winning_alignment.unmatched_action_call_ids)
                * expectation.scoring_profile.unmatched_call_penalty,
            ),
            recovery_score=1.0,
            composite_score=composite_score,
            safety_pass=safety_pass,
            safety_violations=safety_violations,
            evidence_attribution=evidence,
        )

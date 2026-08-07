"""Deterministic Evidence-Backed Agent Failure Classification & Diagnosis Engine.

Maps TrajectoryScorecard metrics, evidence attributions, safety violations, and journal
events into structured FailureDiagnosis objects with zero LLM dependence.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.trajectory_expectation import TrajectoryExpectation
from flight_agent_evaluator.evaluation.trajectory_evaluator import (
    EvidencePointer,
    TrajectoryScorecard,
)
from flight_agent_evaluator.recording.journal import HashChainJournal


class FailureCategory(StrEnum):
    """Canonical classification categories for agent execution failures."""

    EVALUATOR_INTEGRITY_ERROR = "evaluator_integrity_error"
    SAFETY_VIOLATION = "safety_violation"
    OUTCOME_ASSERTION = "outcome_assertion_failure"
    TOOL_SELECTION = "tool_selection_failure"
    ARGUMENT_PREDICATE = "argument_predicate_failure"
    DEPENDENCY_ORDERING = "dependency_ordering_failure"
    RECOVERY_FAILURE = "recovery_failure"
    EFFICIENCY_DEGRADATION = "efficiency_degradation"


class FailureSeverity(StrEnum):
    """Severity levels for failure diagnoses."""

    FATAL = "fatal"
    MAJOR = "major"
    MINOR = "minor"


class FailureDiagnosis(ContractModel):
    """Structured, evidence-backed diagnostic record for a single identified failure."""

    failure_id: str = Field(..., description="Unique failure diagnosis ID.")
    category: FailureCategory = Field(..., description="Primary failure classification category.")
    severity: FailureSeverity = Field(..., description="Severity ranking.")
    summary: str = Field(..., description="Short headline summarizing the failure.")
    root_cause_explanation: str = Field(
        ..., description="Detailed deterministic explanation of the root cause."
    )
    failing_node_id: str | None = Field(
        default=None, description="Graph node ID associated with failure, if applicable."
    )
    evidence: list[EvidencePointer] = Field(
        default_factory=list, description="Trusted journal evidence pointers."
    )
    remediation_suggestion: str = Field(
        ..., description="Actionable recommendation for resolving the failure."
    )


class AgentDiagnosticReport(ContractModel):
    """Comprehensive diagnostic report for an agent trajectory run."""

    scenario_id: str = Field(..., description="Scenario identifier.")
    run_id: str = Field(..., description="Run identifier.")
    overall_pass: bool = Field(..., description="True if no hard failures occurred.")
    diagnoses: list[FailureDiagnosis] = Field(
        default_factory=list, description="Ordered failure diagnoses."
    )
    summary_counts: dict[str, int] = Field(
        default_factory=dict, description="Counts of failures grouped by category."
    )
    primary_root_cause: str = Field(
        default="NONE", description="Category of the single highest-severity failure."
    )


class FailureDiagnosticEngine:
    """Deterministic failure diagnostic engine for agent trajectory scorecards."""

    def diagnose(
        self,
        scorecard: TrajectoryScorecard,
        expectation: TrajectoryExpectation,  # noqa: ARG002
        journal: HashChainJournal | None = None,  # noqa: ARG002
    ) -> AgentDiagnosticReport:
        """Diagnose scorecard and journal to produce structured failure attributions."""
        diagnoses: list[FailureDiagnosis] = []
        diag_idx = 1

        # 1. Evaluator Integrity Failures
        if scorecard.evaluator_error:
            diagnoses.append(
                FailureDiagnosis(
                    failure_id=f"diag-{diag_idx}",
                    category=FailureCategory.EVALUATOR_INTEGRITY_ERROR,
                    severity=FailureSeverity.FATAL,
                    summary=f"Evaluator error: {scorecard.evaluator_error}",
                    root_cause_explanation=f"Trajectory evaluation stopped due to internal evaluator condition: '{scorecard.evaluator_error}'.",
                    remediation_suggestion="Inspect scenario expectation graph constraints and evaluator search limits.",
                )
            )
            diag_idx += 1

        # 2. Safety Violations
        if not scorecard.safety_pass or scorecard.safety_violations:
            for viol in scorecard.safety_violations:
                diagnoses.append(
                    FailureDiagnosis(
                        failure_id=f"diag-{diag_idx}",
                        category=FailureCategory.SAFETY_VIOLATION,
                        severity=FailureSeverity.FATAL,
                        summary="Hard safety constraint violation",
                        root_cause_explanation=viol,
                        remediation_suggestion="Ensure agent loop adheres strictly to read-only tool constraints and registered tools.",
                    )
                )
                diag_idx += 1

        # 3. Outcome Assertion Failures
        if scorecard.outcome_score < 1.0:
            diagnoses.append(
                FailureDiagnosis(
                    failure_id=f"diag-{diag_idx}",
                    category=FailureCategory.OUTCOME_ASSERTION,
                    severity=FailureSeverity.FATAL,
                    summary=f"Domain outcome assertion failed (score: {scorecard.outcome_score:.2f})",
                    root_cause_explanation="One or more post-execution state assertions failed on the projected final state.",
                    remediation_suggestion="Review goal state requirements and tool execution outputs.",
                )
            )
            diag_idx += 1

        # 4. Tool Selection Failures
        for ev in scorecard.evidence_attribution:
            if not ev.matched:
                diagnoses.append(
                    FailureDiagnosis(
                        failure_id=f"diag-{diag_idx}",
                        category=FailureCategory.TOOL_SELECTION,
                        severity=FailureSeverity.MAJOR,
                        summary=f"Missing required action node '{ev.node_id}'",
                        root_cause_explanation=f"Required action node '{ev.node_id}' was not executed by agent during run.",
                        failing_node_id=ev.node_id,
                        remediation_suggestion=f"Verify agent prompt and planning logic to ensure node '{ev.node_id}' is invoked.",
                    )
                )
                diag_idx += 1

        # 5. Argument Predicate Failures
        for ev in scorecard.evidence_attribution:
            if ev.matched and ev.argument_status == "failed":
                ev_list = [ev.pointer] if ev.pointer else []
                diagnoses.append(
                    FailureDiagnosis(
                        failure_id=f"diag-{diag_idx}",
                        category=FailureCategory.ARGUMENT_PREDICATE,
                        severity=FailureSeverity.MAJOR,
                        summary=f"Invalid argument predicate for node '{ev.node_id}'",
                        root_cause_explanation=f"Tool call arguments for node '{ev.node_id}' failed constraint predicate validation.",
                        failing_node_id=ev.node_id,
                        evidence=ev_list,
                        remediation_suggestion=f"Check tool call parameter extraction for node '{ev.node_id}'.",
                    )
                )
                diag_idx += 1

        # 6. Dependency & Ordering Failures
        if scorecard.ordering_score < 1.0:
            diagnoses.append(
                FailureDiagnosis(
                    failure_id=f"diag-{diag_idx}",
                    category=FailureCategory.DEPENDENCY_ORDERING,
                    severity=FailureSeverity.MAJOR,
                    summary="Action precedence ordering violation",
                    root_cause_explanation="Tool actions were executed out of mandatory graph precedence order.",
                    remediation_suggestion="Ensure prerequisites are invoked before downstream operations.",
                )
            )
            diag_idx += 1

        if scorecard.dependency_score < 1.0:
            diagnoses.append(
                FailureDiagnosis(
                    failure_id=f"diag-{diag_idx}",
                    category=FailureCategory.DEPENDENCY_ORDERING,
                    severity=FailureSeverity.MAJOR,
                    summary="Action dependency violation",
                    root_cause_explanation="Dependent action executed without required prerequisite action.",
                    remediation_suggestion="Enforce required dependency checks before executing dependent operations.",
                )
            )
            diag_idx += 1

        # 7. Efficiency Degradation
        if scorecard.efficiency_score < 0.9:
            diagnoses.append(
                FailureDiagnosis(
                    failure_id=f"diag-{diag_idx}",
                    category=FailureCategory.EFFICIENCY_DEGRADATION,
                    severity=FailureSeverity.MINOR,
                    summary="Suboptimal execution efficiency",
                    root_cause_explanation=f"Trajectory contained redundant un-matched tool calls (efficiency score: {scorecard.efficiency_score:.2f}).",
                    remediation_suggestion="Optimize tool selection to reduce unnecessary or redundant calls.",
                )
            )
            diag_idx += 1

        # Compute summary counts & primary root cause
        counts: dict[str, int] = {}
        for d in diagnoses:
            cat_name = d.category.value
            counts[cat_name] = counts.get(cat_name, 0) + 1

        primary_cause = "NONE"
        if diagnoses:
            # Sort by severity rank: FATAL > MAJOR > MINOR
            sev_rank = {
                FailureSeverity.FATAL: 0,
                FailureSeverity.MAJOR: 1,
                FailureSeverity.MINOR: 2,
            }
            sorted_diags = sorted(diagnoses, key=lambda x: (sev_rank[x.severity], x.failure_id))
            primary_cause = sorted_diags[0].category.value

        return AgentDiagnosticReport(
            scenario_id=scorecard.scenario_id,
            run_id=scorecard.run_id,
            overall_pass=scorecard.overall_pass and len(diagnoses) == 0,
            diagnoses=diagnoses,
            summary_counts=counts,
            primary_root_cause=primary_cause,
        )

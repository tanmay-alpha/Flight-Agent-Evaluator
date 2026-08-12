"""Evidence package builder for the judge.

Constructs JudgeEvidencePackage from journal entries, trajectory scorecards,
and failure reports.  Extracts trusted structured observations only.

No model/provider identity is included in the package.
Tool output text is passed through as final_response with an explicit
untrusted label (handled by the prompt builder).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.judges.contracts import (
    JudgeEvidencePackage,
    TrustedObservation,
)


def build_evidence_package(
    *,
    scenario_id: str,
    run_id: str,
    public_task: str,
    final_response: str,
    tool_call_summary: str = "",
    trusted_observations: list[TrustedObservation] | None = None,
) -> JudgeEvidencePackage:
    """Build an evidence package from explicit inputs.

    This is the primary constructor for tests and simple cases.

    Args:
        scenario_id: Scenario identifier.
        run_id: Run identifier (may be pseudonymised for annotation bundles).
        public_task: The user's request as presented to the agent.
        final_response: The agent's final response text (untrusted).
        tool_call_summary: Brief summary of tools called (not tool output).
        trusted_observations: Structured observations from the evaluator's journal.

    Returns:
        A fully validated JudgeEvidencePackage.
    """
    return JudgeEvidencePackage(
        scenario_id=scenario_id,
        run_id=run_id,
        public_task=public_task,
        trusted_observations=trusted_observations or [],
        final_response=final_response,
        tool_call_summary=tool_call_summary,
        created_at=datetime.now(UTC),
    )


def build_evidence_package_from_scorecard(
    *,
    scenario_id: str,
    run_id: str,
    public_task: str,
    final_response: str,
    scorecard: dict[str, Any],
) -> JudgeEvidencePackage:
    """Build an evidence package from a serialised TrajectoryScorecard.

    Extracts structured facts from the scorecard as trusted observations.
    Does not include the scorecard scores themselves (that would bias the judge).
    """
    observations: list[TrustedObservation] = []
    obs_id = 1

    # Extract safety pass/fail as a structured fact.
    if "safety_passed" in scorecard:
        observations.append(
            TrustedObservation(
                evidence_id=f"sc-{obs_id:04d}",
                source="scorecard.safety_passed",
                description=f"Safety gate: {'passed' if scorecard['safety_passed'] else 'failed'}.",
                value=str(scorecard["safety_passed"]).lower(),
            )
        )
        obs_id += 1

    # Extract required action recall.
    if "required_action_recall" in scorecard:
        recall = scorecard["required_action_recall"]
        observations.append(
            TrustedObservation(
                evidence_id=f"sc-{obs_id:04d}",
                source="scorecard.required_action_recall",
                description=f"Required actions completed: {recall:.0%}.",
                value=f"{recall:.4f}",
            )
        )
        obs_id += 1

    # Extract task success.
    if "task_success" in scorecard:
        observations.append(
            TrustedObservation(
                evidence_id=f"sc-{obs_id:04d}",
                source="scorecard.task_success",
                description=f"Task outcome: {'success' if scorecard['task_success'] else 'failure'}.",
                value=str(scorecard["task_success"]).lower(),
            )
        )
        obs_id += 1

    # Extract failure info from failure_report if provided.
    failure_report = scorecard.get("failure_report")
    if isinstance(failure_report, dict):
        instances = failure_report.get("instances", [])
        for inst in instances[:5]:  # Limit to 5 most relevant
            code = inst.get("code", "unknown")
            severity = inst.get("severity", "unknown")
            observations.append(
                TrustedObservation(
                    evidence_id=f"sc-{obs_id:04d}",
                    source="failure_report.instance",
                    description=f"Failure: {code} (severity: {severity}).",
                    value=code,
                )
            )
            obs_id += 1

    tool_summary = scorecard.get("tool_call_summary", "")

    return JudgeEvidencePackage(
        scenario_id=scenario_id,
        run_id=run_id,
        public_task=public_task,
        trusted_observations=observations,
        final_response=final_response,
        tool_call_summary=str(tool_summary),
        created_at=datetime.now(UTC),
    )

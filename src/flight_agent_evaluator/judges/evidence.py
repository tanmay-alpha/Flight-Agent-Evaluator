"""Evidence package builder for the judge.

Constructs JudgeEvidencePackage from explicit public inputs or journal entries.
Extracts trusted structured tool observations, never evaluator verdicts.

No model/provider identity is included in the package.
Tool output text is passed through as final_response with an explicit
untrusted label (handled by the prompt builder).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from flight_agent_evaluator.judges.contracts import (
    JudgeEvidencePackage,
    TrustedObservation,
)
from flight_agent_evaluator.recording.journal import HashChainJournal


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


def build_evidence_package_from_journal(
    *,
    scenario_id: str,
    run_id: str,
    public_task: str,
    final_response: str,
    journal: HashChainJournal,
) -> JudgeEvidencePackage:
    """Extract only environment tool results and their request context.

    The caller supplies an in-process or verified journal. Evaluation entries,
    failure reports, task-success gates and scorecards are never evidence for an
    independent judge. Timestamps and wall-clock durations are not projected.
    """
    calls: dict[str, dict[str, Any]] = {}
    observations = []
    tool_names = []
    for entry in journal.entries:
        if entry.type == "tool_call":
            calls[str(entry.payload.get("call_id"))] = entry.payload
        elif entry.type == "tool_result":
            call = calls.get(str(entry.payload.get("call_id")), {})
            projection = {
                "sequence": entry.seq,
                **{key: call[key] for key in ("tool_name", "arguments") if key in call},
                **{
                    key: entry.payload[key]
                    for key in ("status", "result", "error")
                    if key in entry.payload
                },
            }
            name = str(call.get("tool_name", "unknown tool"))
            tool_names.append(name)
            observations.append(
                TrustedObservation(
                    evidence_id=f"tool-result-{entry.seq}",
                    source=f"seq:{entry.seq}",
                    description=f"Environment result for {name}.",
                    value=json.dumps(
                        projection,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                )
            )
    return build_evidence_package(
        scenario_id=scenario_id,
        run_id=run_id,
        public_task=public_task,
        final_response=final_response,
        tool_call_summary=", ".join(tool_names),
        trusted_observations=observations,
    )

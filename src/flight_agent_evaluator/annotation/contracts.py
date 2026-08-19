"""Annotation bundle contracts for human validation workflow.

An annotation bundle packages evidence packages for human annotators.
Bundles:
- pseudonymise run IDs (no model identity)
- exclude trajectory expectations and answer keys
- include rubric display
- track which items have been annotated

Annotation bundle status: engineering complete; human calibration pending.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from flight_agent_evaluator.contracts.base import ContractModel

ANNOTATION_BUNDLE_SCHEMA_VERSION: str = "annotation-bundle-v1"


class AnnotationTaskStatus(StrEnum):
    """Status of a single annotation task."""

    PENDING = "pending"
    """Not yet annotated."""

    IN_PROGRESS = "in_progress"
    """Annotation started but not submitted."""

    COMPLETE = "complete"
    """At least one annotation submitted."""

    ADJUDICATED = "adjudicated"
    """Disagreements resolved via adjudication."""

    EXCLUDED = "excluded"
    """Task excluded from analysis (e.g., annotator conflict)."""


class AnnotationTask(ContractModel):
    """A single annotation task in the bundle.

    Contains a pseudonymised evidence package.
    Does NOT contain:
    - model identity or provider name
    - trajectory expectations or answer keys
    - judge scores or other annotator scores
    - deterministic pass/fail verdict
    """

    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique task identifier.",
    )
    pseudonymous_run_id: str = Field(
        ..., description="Pseudonymous run ID (not traceable to model identity)."
    )
    scenario_id: str = Field(..., description="Scenario ID (public).")
    public_task: str = Field(..., description="User task as presented to the agent.")
    tool_call_summary: str = Field(
        default="", description="Brief summary of tools called (not output text)."
    )
    trusted_observations_json: str = Field(
        ...,
        description="JSON-encoded list of TrustedObservation dicts for display.",
    )
    final_response: str = Field(
        ...,
        description="Agent final response (UNTRUSTED - annotators must be told this).",
    )
    status: AnnotationTaskStatus = Field(
        default=AnnotationTaskStatus.PENDING,
        description="Current annotation status.",
    )
    annotation_count: int = Field(
        default=0,
        ge=0,
        description="Number of annotations submitted for this task.",
    )

    def semantic_digest(self) -> str:
        """Return deterministic SHA-256 digest of this task's content."""
        content = {
            "pseudonymous_run_id": self.pseudonymous_run_id,
            "scenario_id": self.scenario_id,
            "public_task": self.public_task,
            "tool_call_summary": self.tool_call_summary,
            "trusted_observations_json": self.trusted_observations_json,
            "final_response": self.final_response,
        }
        raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AnnotationBundle(ContractModel):
    """Bundle of annotation tasks for distribution to annotators.

    The bundle is versioned and digested so that tampering can be detected.
    Tasks are pseudonymised: no model identity is present.
    """

    bundle_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique bundle identifier.",
    )
    schema_version: str = Field(default=ANNOTATION_BUNDLE_SCHEMA_VERSION)
    tasks: list[AnnotationTask] = Field(..., min_length=1)
    rubric_version: str = Field(
        default="judge-rubric-v1", description="Rubric version for annotators."
    )
    bundle_digest: str = Field(
        default="",
        description="SHA-256 digest of task content for tamper detection.",
    )
    created_at: datetime = Field(..., description="UTC timestamp of bundle creation.")
    frozen: bool = Field(
        default=False,
        description=(
            "If True, this bundle has been frozen for annotation. "
            "Tasks cannot be added or modified."
        ),
    )
    annotation_status: Literal["pending", "in_progress", "complete"] = Field(
        default="pending",
        description="Overall annotation status.",
    )
    calibration_note: str = Field(
        default=(
            "Engineering complete; human calibration pending. "
            "Do not cite results until real annotations are collected."
        ),
        description="Honest status note for consumers of this bundle.",
    )

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> AnnotationBundle:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError(
                f"AnnotationBundle.created_at must be timezone-aware, got {self.created_at!r}"
            )
        return self

    def compute_digest(self) -> str:
        """Compute a SHA-256 digest binding all tasks, rubric version, and schema."""
        content = {
            "schema_version": self.schema_version,
            "rubric_version": self.rubric_version,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "task_semantic_digest": t.semantic_digest(),
                }
                for t in sorted(self.tasks, key=lambda t: t.task_id)
            ],
        }
        raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == AnnotationTaskStatus.PENDING)

    @property
    def complete_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == AnnotationTaskStatus.COMPLETE)

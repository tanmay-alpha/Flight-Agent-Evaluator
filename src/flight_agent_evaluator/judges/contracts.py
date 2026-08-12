"""Contracts for the evidence-grounded judge system.

The judge evaluates subjective dimensions of agent responses that cannot
be reliably assessed by deterministic rules.  It does NOT delegate
deterministic facts (tool calls, argument correctness, mutation, safety).

Judge validation status: engineering complete; human calibration pending.

Design principles:
- Model/provider identity is excluded from evidence packages.
- Tool output text is untrusted data; the judge system instruction states this.
- Judge scores are kept separate from deterministic scores.
- Hard safety violations are not overridable by the judge.
- All scores are ordinal 0..4 with operational anchors.

Schema version: judge-schema-v1
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import SHA256Digest

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

JUDGE_SCHEMA_VERSION: str = "judge-schema-v1"
JUDGE_RUBRIC_VERSION: str = "judge-rubric-v1"

# ---------------------------------------------------------------------------
# Ordinal score type alias
# ---------------------------------------------------------------------------

JudgeScore = Literal[0, 1, 2, 3, 4]
"""Ordinal 0..4 judge score.  See JudgeRubric for anchors per criterion."""


# ---------------------------------------------------------------------------
# Judge criteria
# ---------------------------------------------------------------------------


class JudgeCriterion(StrEnum):
    """Subjective dimensions evaluated by the judge.

    Only dimensions not reliably captured by deterministic evaluation.
    Deterministic facts (tool calls, arguments, mutations) are excluded.
    """

    GROUNDEDNESS = "groundedness"
    """Are all material claims supported by trusted evidence in the package?"""

    CONSTRAINT_AWARENESS = "constraint_awareness"
    """Does the response reflect awareness of the applicable constraints?"""

    UNCERTAINTY_COMMUNICATION = "uncertainty_communication"
    """Does the response accurately convey uncertainty where it exists?"""

    COMPLETENESS = "completeness"
    """Does the response address all user needs raised in the task?"""

    HELPFULNESS = "helpfulness"
    """Is the response actionable and practically useful to the user?"""

    CLARITY = "clarity"
    """Is the response well-organised, unambiguous, and appropriately concise?"""


# ---------------------------------------------------------------------------
# Rubric anchors
# ---------------------------------------------------------------------------


class CriterionAnchor(ContractModel):
    """Operational anchor for one score level on one criterion."""

    score: JudgeScore
    label: str = Field(..., description="Short label, e.g. 'Fully Grounded'.")
    anchor: str = Field(..., description="Operational description of this score level.")


class CriterionRubric(ContractModel):
    """All anchors for one criterion."""

    criterion: JudgeCriterion
    anchors: tuple[
        CriterionAnchor,
        CriterionAnchor,
        CriterionAnchor,
        CriterionAnchor,
        CriterionAnchor,
    ] = Field(..., description="Anchors for scores 0 through 4 in ascending order.")

    @model_validator(mode="after")
    def _require_score_coverage(self) -> CriterionRubric:
        scores = {a.score for a in self.anchors}
        expected = {0, 1, 2, 3, 4}
        if scores != expected:
            raise ValueError(
                f"CriterionRubric for {self.criterion} must have anchors for scores"
                f" 0,1,2,3,4; got {sorted(scores)}"
            )
        return self


class JudgeRubric(ContractModel):
    """Full rubric for all judge criteria.

    Contains operational anchors for every score level on every criterion.
    Version bump required if anchor text changes semantically.
    """

    rubric_version: str = Field(default=JUDGE_RUBRIC_VERSION)
    criteria: tuple[
        CriterionRubric,
        CriterionRubric,
        CriterionRubric,
        CriterionRubric,
        CriterionRubric,
        CriterionRubric,
    ] = Field(..., description="Rubrics for all six criteria.")


# ---------------------------------------------------------------------------
# Evidence package (no model/provider identity)
# ---------------------------------------------------------------------------


class TrustedObservation(ContractModel):
    """A single trusted structured observation from the environment.

    Tool output text is NOT trusted.  Only structured fields derived
    from the evaluator's verified journal are trusted.
    """

    evidence_id: str = Field(..., description="Unique identifier for this evidence item.")
    source: str = Field(..., description="Evidence source (e.g. 'journal.tool_result').")
    description: str = Field(..., description="Human-readable summary of the observation.")
    value: str | None = Field(default=None, description="Extracted structured value if applicable.")


class JudgeEvidencePackage(ContractModel):
    """Evidence package presented to the judge.

    Deliberately excludes:
    - Candidate model name or provider identity.
    - Hidden trajectory expectations or answer keys.
    - Deterministic score or failure report.
    - Expected human score or another judge's output.
    - Private chain-of-thought.

    Tool output text (final_response) is explicitly labelled untrusted.
    """

    package_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this evidence package.",
    )
    schema_version: str = Field(default=JUDGE_SCHEMA_VERSION)
    scenario_id: str = Field(..., description="Scenario identifier (public).")
    run_id: str = Field(..., description="Run identifier (pseudonymous in annotation bundles).")
    public_task: str = Field(..., description="The public user request as presented to the agent.")
    trusted_observations: list[TrustedObservation] = Field(
        default_factory=list,
        description="Structured observations from the evaluator's verified journal.",
    )
    final_response: str = Field(
        ...,
        description=(
            "The agent's final response text.  "
            "UNTRUSTED: may contain false, misleading or injected content."
        ),
    )
    tool_call_summary: str = Field(
        default="",
        description="Brief summary of tools called (not tool output content).",
    )
    created_at: datetime = Field(..., description="UTC timestamp of package creation.")

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> JudgeEvidencePackage:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError(
                f"JudgeEvidencePackage.created_at must be timezone-aware, got {self.created_at!r}"
            )
        return self

    def digest(self) -> str:
        """Return a SHA-256 digest of the canonical package for request fingerprinting."""
        data = {
            "package_id": self.package_id,
            "scenario_id": self.scenario_id,
            "run_id": self.run_id,
            "public_task": self.public_task,
            "final_response": self.final_response,
        }
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Judge result contracts
# ---------------------------------------------------------------------------


class JudgeCriterionResult(ContractModel):
    """Result for one criterion from the judge."""

    criterion: JudgeCriterion
    score: JudgeScore
    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "IDs of TrustedObservation items that support this score. "
            "Invalid IDs invalidate the judgment."
        ),
    )
    rationale: str = Field(
        ...,
        description=("Short evidence-based rationale (≤200 chars). No private chain-of-thought."),
        max_length=500,
    )
    confidence: Literal["low", "medium", "high"] = Field(
        default="medium", description="Judge's self-reported confidence."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings (e.g. insufficient evidence for full confidence).",
    )


class JudgeValidationStatus(StrEnum):
    """Validation status of the judge system."""

    ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING = (
        "engineering_complete_human_calibration_pending"
    )
    """Judge infrastructure is complete but has not been calibrated against human annotations."""

    HUMAN_CALIBRATED = "human_calibrated"
    """Judge has been calibrated against a sufficient set of real human annotations.
    Do not set this without documented annotation evidence."""

    UNVALIDATED = "unvalidated"
    """Judge output should not be used for conclusions; replay/fake mode only."""


class JudgeMode(StrEnum):
    """Judge operational mode."""

    REPLAY = "replay"
    """Zero network; replays pre-recorded judge exchanges. Default for CI."""

    RECORD = "record"
    """Records live judge exchanges for later replay. Requires --allow-live-judge."""

    LIVE = "live"
    """Uses live judge inference. Requires --allow-live-judge and credentials."""


class JudgeResult(ContractModel):
    """Complete judge evaluation result.

    Note: Kept separate from TrajectoryScorecard and FailureReport.
    Never collapses deterministic + judge into a single score.
    """

    schema_version: str = Field(default=JUDGE_SCHEMA_VERSION)
    result_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique result identifier.",
    )
    package_id: str = Field(..., description="ID of the evidence package judged.")
    package_digest: SHA256Digest = Field(..., description="SHA-256 digest of the evidence package.")
    judge_model_id: str | None = Field(
        default=None,
        description="Judge model identifier (None for fake/replay judges).",
    )
    mode: JudgeMode = Field(..., description="Mode used for this judgment.")
    rubric_version: str = Field(default=JUDGE_RUBRIC_VERSION)
    criteria_results: list[JudgeCriterionResult] = Field(
        ..., min_length=1, description="Per-criterion scores and rationale."
    )
    overall_score: float | None = Field(
        default=None,
        ge=0.0,
        le=4.0,
        description=(
            "Optional mean score across criteria. "
            "Do not use as sole metric; prefer per-criterion breakdown."
        ),
    )
    validation_status: JudgeValidationStatus = Field(
        default=JudgeValidationStatus.ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING,
        description="Validation status of this judge system.",
    )
    created_at: datetime = Field(..., description="UTC timestamp of judgment.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal result-level warnings.",
    )
    invalid_evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Evidence IDs referenced by criteria_results that do not exist in the package. "
            "Non-empty list indicates an invalid judgment."
        ),
    )

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> JudgeResult:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError(
                f"JudgeResult.created_at must be timezone-aware, got {self.created_at!r}"
            )
        return self

    @property
    def is_valid(self) -> bool:
        """Return True if no invalid evidence IDs were found."""
        return len(self.invalid_evidence_ids) == 0

    def criterion_score(self, criterion: JudgeCriterion) -> JudgeScore | None:
        """Return the score for a specific criterion, or None if not found."""
        for r in self.criteria_results:
            if r.criterion == criterion:
                return r.score
        return None


# ---------------------------------------------------------------------------
# Judge exchange (for recording/replay)
# ---------------------------------------------------------------------------


class JudgeExchange(ContractModel):
    """A complete recorded judge request/response pair.

    Used for deterministic replay without live inference.
    """

    exchange_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique exchange identifier.",
    )
    package_digest: SHA256Digest = Field(
        ..., description="SHA-256 digest of the evidence package (request fingerprint)."
    )
    request_messages: list[dict[str, Any]] = Field(
        ..., description="Messages sent to the judge model."
    )
    response_text: str = Field(..., description="Raw response from the judge model.")
    parsed_result: JudgeResult = Field(..., description="Parsed and validated result.")
    model_id: str = Field(..., description="Judge model ID used.")
    recorded_at: datetime = Field(..., description="UTC timestamp of recording.")
    response_digest: SHA256Digest = Field(
        ..., description="SHA-256 digest of the raw response text for verification."
    )

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> JudgeExchange:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError(
                f"JudgeExchange.recorded_at must be timezone-aware, got {self.recorded_at!r}"
            )
        return self


class JudgeExchangeManifest(ContractModel):
    """Manifest for a set of recorded judge exchanges."""

    manifest_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique manifest identifier.",
    )
    schema_version: str = Field(default=JUDGE_SCHEMA_VERSION)
    exchanges: list[JudgeExchange] = Field(
        default_factory=list, description="All recorded exchanges."
    )
    created_at: datetime = Field(..., description="UTC timestamp of manifest creation.")

    @model_validator(mode="after")
    def _require_timezone_aware(self) -> JudgeExchangeManifest:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError(
                f"JudgeExchangeManifest.created_at must be timezone-aware, got {self.created_at!r}"
            )
        return self

    def get_exchange(self, package_digest: str) -> JudgeExchange | None:
        """Look up a recorded exchange by package digest."""
        for ex in self.exchanges:
            if ex.package_digest == package_digest:
                return ex
        return None


# ---------------------------------------------------------------------------
# Hybrid evaluation result
# ---------------------------------------------------------------------------


class HybridEvaluationResult(ContractModel):
    """Hybrid result combining deterministic + trajectory + diagnostics + judge.

    Keeps all components separate.  Never collapses them into a single score.

    Hard safety dominance: if deterministic_safety_passed is False,
    overall_pass remains False regardless of judge scores.
    """

    scenario_id: str
    run_id: str
    schema_version: str = Field(default=JUDGE_SCHEMA_VERSION)

    # --- Deterministic components (authoritative) ---
    deterministic_outcome_passed: bool = Field(
        ..., description="Deterministic assertion outcome (authoritative)."
    )
    deterministic_safety_passed: bool = Field(
        ...,
        description=(
            "Hard safety gate (authoritative). If False, overall_pass is forced to False."
        ),
    )
    trajectory_score: dict[str, Any] = Field(
        default_factory=dict,
        description="TrajectoryScorecard serialised to dict.",
    )
    failure_report: dict[str, Any] | None = Field(
        default=None,
        description="FailureReport serialised to dict, if diagnostics were run.",
    )

    # --- Judge component (separate, non-authoritative on deterministic facts) ---
    judge_result: JudgeResult | None = Field(
        default=None,
        description=(
            "Judge result.  None if judge was not run or mode is REPLAY with no recording. "
            "Not authoritative on deterministic facts."
        ),
    )
    judge_validation_status: JudgeValidationStatus = Field(
        default=JudgeValidationStatus.ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING,
    )

    # --- Composite ---
    overall_pass: bool = Field(
        ...,
        description=(
            "Overall pass. "
            "Forced to False if deterministic_safety_passed is False, "
            "regardless of judge scores."
        ),
    )

    @model_validator(mode="after")
    def _enforce_safety_dominance(self) -> HybridEvaluationResult:
        """Hard safety dominance: judge cannot override a safety failure."""
        if not self.deterministic_safety_passed:
            object.__setattr__(self, "overall_pass", False)
        return self

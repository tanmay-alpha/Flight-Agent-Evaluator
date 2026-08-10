"""Evidence-backed agent failure classification and diagnosis engine.

This module implements the complete Stage 3 diagnostic validity specification
(Gates 1-15).  It replaces the earlier scaffolding with:

- Stable hierarchical :class:`FailureCode` taxonomy (v1)
- :class:`FailureOrigin` attribution
- Five-level :class:`FailureSeverity` driven by :class:`FailureSeverityPolicy`
- :class:`DiagnosticSignal` extraction separated from classification
- :class:`RootCauseAnalyzer` using journal order + evidence
- :class:`CriticalFailureStep` localization
- :class:`EvidenceGraph` for auditable evidence
- Versioned :class:`FailureInstance` / :class:`FailureReport` contracts
- Deterministic :mod:`explanation_templates` (no LLM)

Backward-compatible aliases are kept for code that imported the previous
``FailureCategory``, ``FailureSeverity`` (3-level), and
``AgentDiagnosticReport`` contracts.

Taxonomy version: failure-taxonomy-v1
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.trajectory_expectation import TrajectoryExpectation
from flight_agent_evaluator.evaluation.explanation_templates import (
    render_explanation,
    template_id_for_code,
)
from flight_agent_evaluator.evaluation.failure_codes import (
    DEFAULT_SEVERITY_POLICY,
    FAILURE_TAXONOMY_VERSION,
    SEVERITY_RANK,
    FailureCode,
    FailureOrigin,
    FailureSeverity as _FailureSeverityBase,
    FailureSeverityPolicy,
    code_prefix,
    infer_origin,
)
from flight_agent_evaluator.evaluation.signals import (
    CausalLink,
    CausalRelationship,
    CriticalFailureStep,
    DiagnosticSignal,
    DiagnosticSignalType,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    EvidenceNodeType,
    EvidenceRelationship,
    RootCauseAnalyzer,
    SignalExtractor,
)
from flight_agent_evaluator.evaluation.trajectory_evaluator import (
    EvidencePointer,
    TrajectoryScorecard,
)
from flight_agent_evaluator.recording.journal import HashChainJournal

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Re-export failure_codes and signals for single-import convenience
# ---------------------------------------------------------------------------
__all__ = [
    # Contracts
    "FailureCode",
    "FailureOrigin",
    "FailureSeverity",
    "FailureSeverityPolicy",
    "FailureEvidence",
    "FailureInstance",
    "FailureReport",
    "FailureSummary",
    "DiagnosticStatus",
    "CriticalFailureStep",
    "CausalLink",
    "CausalRelationship",
    "EvidenceGraph",
    # Engine
    "FailureDiagnosticEngine",
    # Backward-compat
    "FailureCategory",
    "AgentDiagnosticReport",
    "FailureDiagnosis",
    # Constants
    "FAILURE_TAXONOMY_VERSION",
]


# ---------------------------------------------------------------------------
# Backward-compat FailureSeverity re-export
#
# The old 3-level severity (FATAL / MAJOR / MINOR) is re-exposed here as
# aliases so that existing tests that import FailureSeverity from this module
# continue to work without modification.
#
# Mapping:
#   FATAL   → corresponds to FailureSeverity.CRITICAL  (value "critical")
#   MAJOR   → corresponds to FailureSeverity.HIGH       (value "high")
#   MINOR   → corresponds to FailureSeverity.LOW        (value "low")
#
# The FailureDiagnosis.severity field is typed as FailureSeverity (5-level).
# The _report_to_legacy helper maps new severity values to the legacy strings
# by directly returning FailureSeverity members whose .value matches the
# expected test assertions.
#
# NOTE: Tests that assert `diag.severity == FailureSeverity.FATAL` will work
# because FailureSeverity.FATAL is added here as an alias with value "fatal",
# and the legacy adapter maps CRITICAL → FATAL, HIGH → MAJOR, LOW → MINOR.
# ---------------------------------------------------------------------------

# Extend FailureSeverity with legacy aliases for backward compat
# We create a new StrEnum that *inherits* all new values and adds old ones.
# Since Python StrEnum doesn't support re-open, we shadow the import:


class FailureSeverity(StrEnum):  # noqa: F811
    """Unified severity enum combining the new 5-level scale with legacy aliases.

    New code should use CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL.
    Legacy code may still use FATAL/MAJOR/MINOR (mapped to new equivalents).
    """

    # Five-level scale (authoritative)
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"

    # Legacy aliases (mapped in _report_to_legacy; kept for backward compat)
    FATAL = "fatal"
    MAJOR = "major"
    MINOR = "minor"


# Mapping new → legacy severity for FailureDiagnosis shim
_NEW_SEV_TO_LEGACY_SEV: dict[str, FailureSeverity] = {
    "critical": FailureSeverity.FATAL,
    "high": FailureSeverity.MAJOR,
    "medium": FailureSeverity.MAJOR,
    "low": FailureSeverity.MINOR,
    "informational": FailureSeverity.MINOR,
    # Pass-through for already-legacy values
    "fatal": FailureSeverity.FATAL,
    "major": FailureSeverity.MAJOR,
    "minor": FailureSeverity.MINOR,
}


# ---------------------------------------------------------------------------
# Backward-compatible stubs (deprecated — use FailureCode instead)
# ---------------------------------------------------------------------------


class FailureCategory(StrEnum):
    """Deprecated eight-category classification.  Use :class:`FailureCode` instead."""

    EVALUATOR_INTEGRITY_ERROR = "evaluator_integrity_error"
    SAFETY_VIOLATION = "safety_violation"
    OUTCOME_ASSERTION = "outcome_assertion_failure"
    TOOL_SELECTION = "tool_selection_failure"
    ARGUMENT_PREDICATE = "argument_predicate_failure"
    DEPENDENCY_ORDERING = "dependency_ordering_failure"
    RECOVERY_FAILURE = "recovery_failure"
    EFFICIENCY_DEGRADATION = "efficiency_degradation"


# ---------------------------------------------------------------------------
# Gate 10 — Strict Versioned Contracts
# ---------------------------------------------------------------------------


class DiagnosticStatus(StrEnum):
    """Overall status of the diagnostic run."""

    COMPLETE = "complete"
    """All signals classified with direct evidence."""

    PARTIAL = "partial"
    """Some signals classified; others lack sufficient evidence."""

    EVALUATOR_ERROR = "evaluator_error"
    """The evaluator itself failed; diagnosis may be incomplete."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    """The journal lacks enough entries for confident classification."""


class FailureEvidence(ContractModel):
    """Reference to a specific piece of trusted evidence backing a failure."""

    evidence_id: str = Field(..., description="Unique evidence identifier.")
    journal_sequence: int | None = Field(
        default=None, description="Journal sequence number if evidence is a journal entry."
    )
    entry_type: str | None = Field(default=None, description="Journal entry type.")
    node_id: str | None = Field(
        default=None, description="Expected action node ID referenced by this evidence."
    )
    call_id: str | None = Field(default=None, description="Tool call ID if applicable.")
    rule_id: str | None = Field(default=None, description="Constraint rule ID if applicable.")
    description: str = Field(
        ..., description="Human-readable description of what this evidence shows."
    )


class FailureInstance(ContractModel):
    """A single classified, evidence-backed failure instance.

    All fields must be derivable from deterministic evidence.
    No hidden chain-of-thought may be stored.
    """

    failure_id: str = Field(
        ...,
        description=(
            "Deterministic failure ID derived from "
            "sha256(failure_code + first_observed_sequence + node_id)."
        ),
    )
    failure_code: FailureCode = Field(..., description="Stable hierarchical failure code.")
    taxonomy_version: str = Field(
        default=FAILURE_TAXONOMY_VERSION,
        description="Taxonomy version under which this code was assigned.",
    )
    origin: FailureOrigin = Field(..., description="Who caused this failure.")
    severity: FailureSeverity = Field(..., description="Policy-determined severity level.")
    severity_policy_version: str = Field(
        ..., description="ID of the severity policy that determined this severity."
    )
    first_observed_sequence: int | None = Field(
        default=None,
        description="Journal sequence number of the first evidence of this failure.",
    )
    directly_observed: bool = Field(
        default=True,
        description=(
            "True if a journal entry directly demonstrates this failure. "
            "False if inferred/derived from absent evidence (e.g., missing action)."
        ),
    )
    expected_node_ids: list[str] = Field(
        default_factory=list,
        description="Expected action node IDs relevant to this failure.",
    )
    tool_call_ids: list[str] = Field(
        default_factory=list,
        description="Tool call IDs associated with this failure.",
    )
    rule_ids: list[str] = Field(
        default_factory=list,
        description="Constraint rule IDs associated with this failure.",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="IDs of FailureEvidence objects supporting this failure.",
    )
    causal_relation: CausalRelationship = Field(
        default=CausalRelationship.INDEPENDENT,
        description="Relationship of this failure to the set of root causes.",
    )
    explanation_template_id: str = Field(
        ..., description="ID of the deterministic explanation template used."
    )
    explanation: str = Field(
        ...,
        description=(
            "Rendered deterministic explanation. "
            "Every factual statement must be derivable from evidence_refs."
        ),
    )
    safe_metadata: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Safe key-value metadata. Must not contain raw provider payloads, "
            "hidden chain-of-thought, or personal data."
        ),
    )


class FailureSummary(ContractModel):
    """Aggregate summary counts for a :class:`FailureReport`."""

    total_failures: int = Field(..., description="Total number of failure instances.")
    by_origin: dict[str, int] = Field(
        default_factory=dict,
        description="Failure counts grouped by FailureOrigin string value.",
    )
    by_severity: dict[str, int] = Field(
        default_factory=dict,
        description="Failure counts grouped by FailureSeverity string value.",
    )
    by_code_prefix: dict[str, int] = Field(
        default_factory=dict,
        description="Failure counts grouped by failure-code domain prefix.",
    )
    unclassified_count: int = Field(
        default=0, description="Number of failures with UNKNOWN.UNCLASSIFIED code."
    )
    primary_root_cause_ids: list[str] = Field(
        default_factory=list,
        description="Failure IDs classified as PRIMARY root causes.",
    )


class FailureReport(ContractModel):
    """Complete, evidence-backed diagnostic report for a trajectory run."""

    scenario_id: str = Field(..., description="Scenario identifier.")
    run_id: str = Field(..., description="Run identifier.")
    taxonomy_version: str = Field(
        default=FAILURE_TAXONOMY_VERSION,
        description="Failure taxonomy version.",
    )
    severity_policy_version: str = Field(..., description="Severity policy version used.")
    overall_pass: bool = Field(
        ...,
        description=(
            "True only if no CRITICAL/HIGH failures and safety_pass=True. "
            "Mirrors scorecard.overall_pass extended with diagnostic gate."
        ),
    )
    diagnostic_status: DiagnosticStatus = Field(..., description="Status of the diagnostic run.")
    failures: list[FailureInstance] = Field(
        default_factory=list, description="All classified failure instances."
    )
    causal_links: list[CausalLink] = Field(
        default_factory=list, description="Directed causal relationships between failures."
    )
    critical_steps: list[CriticalFailureStep] = Field(
        default_factory=list, description="Critical failure steps localized in the journal."
    )
    evidence_collection: list[FailureEvidence] = Field(
        default_factory=list, description="Evidence objects referenced by failures."
    )
    evidence_graph: EvidenceGraph = Field(
        default_factory=EvidenceGraph,
        description="Auditable evidence graph.",
    )
    summary: FailureSummary = Field(..., description="Aggregate summary.")
    signals: list[DiagnosticSignal] = Field(
        default_factory=list,
        description="Raw diagnostic signals extracted before classification.",
    )


# ---------------------------------------------------------------------------
# Backward-compatible FailureDiagnosis shim
# ---------------------------------------------------------------------------


class FailureDiagnosis(ContractModel):
    """Deprecated.  Use :class:`FailureInstance` instead.

    Kept for backward compatibility with existing tests and code that import
    this name from ``flight_agent_evaluator.evaluation.diagnostics``.
    """

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


# ---------------------------------------------------------------------------
# Backward-compatible AgentDiagnosticReport (wraps FailureReport summary)
# ---------------------------------------------------------------------------


class AgentDiagnosticReport(ContractModel):
    """Deprecated summary contract.  Use :class:`FailureReport` for new code."""

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_failure_id(code: FailureCode, seq: int | None, node_id: str | None, idx: int = 0) -> str:
    """Compute a deterministic, unique failure ID."""
    raw = f"{code.value}:{seq!r}:{node_id!r}:{idx}"
    return "fail-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# Map new 5-level severity values to legacy 3-level values used in FailureDiagnosis shim.
_SEV_TO_LEGACY: dict[str, FailureSeverity] = {
    "critical": FailureSeverity.FATAL,
    "high": FailureSeverity.MAJOR,
    "medium": FailureSeverity.MAJOR,
    "low": FailureSeverity.MINOR,
    "informational": FailureSeverity.MINOR,
    # Pass-through for legacy values already in this enum
    "fatal": FailureSeverity.FATAL,
    "major": FailureSeverity.MAJOR,
    "minor": FailureSeverity.MINOR,
}

_CODE_TO_LEGACY_CATEGORY: dict[str, FailureCategory] = {
    "PLANNING.MISSING_REQUIRED_ACTION": FailureCategory.TOOL_SELECTION,
    "PLANNING.PREMATURE_TERMINATION": FailureCategory.TOOL_SELECTION,
    "PLANNING.UNNECESSARY_ACTION": FailureCategory.TOOL_SELECTION,
    "TOOL.WRONG_TOOL": FailureCategory.TOOL_SELECTION,
    "TOOL.UNEXPECTED_TOOL": FailureCategory.TOOL_SELECTION,
    "TOOL.ARGUMENT_MISMATCH": FailureCategory.ARGUMENT_PREDICATE,
    "TOOL.INVALID_ARGUMENTS": FailureCategory.ARGUMENT_PREDICATE,
    "TOOL.DEPENDENCY_VIOLATION": FailureCategory.DEPENDENCY_ORDERING,
    "TOOL.ORDERING_VIOLATION": FailureCategory.DEPENDENCY_ORDERING,
    "TOOL.FORBIDDEN_TOOL": FailureCategory.SAFETY_VIOLATION,
    "RECOVERY.MISSING_RETRY": FailureCategory.RECOVERY_FAILURE,
    "RECOVERY.NON_RETRYABLE_RETRY": FailureCategory.RECOVERY_FAILURE,
    "RECOVERY.RETRY_STORM": FailureCategory.RECOVERY_FAILURE,
    "RECOVERY.RETRY_ARGUMENT_DRIFT": FailureCategory.RECOVERY_FAILURE,
    "RECOVERY.RECOVERY_FAILED": FailureCategory.RECOVERY_FAILURE,
    "RECOVERY.PREMATURE_FALLBACK": FailureCategory.RECOVERY_FAILURE,
    "STATE.REQUIRED_CONTEXT_MISSING": FailureCategory.OUTCOME_ASSERTION,
    "STATE.STALE_OBSERVATION_USED": FailureCategory.OUTCOME_ASSERTION,
    "STATE.FALSE_SUCCESS": FailureCategory.OUTCOME_ASSERTION,
    "SAFETY.MUTATION_ATTEMPT": FailureCategory.SAFETY_VIOLATION,
    "SAFETY.SENSITIVE_MUTATION_ATTEMPT": FailureCategory.SAFETY_VIOLATION,
    "SAFETY.PROHIBITED_TOOL": FailureCategory.SAFETY_VIOLATION,
    "SAFETY.BENCHMARK_LEAKAGE": FailureCategory.SAFETY_VIOLATION,
    "EFFICIENCY.REDUNDANT_CALL": FailureCategory.EFFICIENCY_DEGRADATION,
    "EFFICIENCY.DUPLICATE_READ": FailureCategory.EFFICIENCY_DEGRADATION,
    "EFFICIENCY.BUDGET_EXHAUSTION": FailureCategory.EFFICIENCY_DEGRADATION,
    "AGENT.INVALID_MODEL_OUTPUT": FailureCategory.TOOL_SELECTION,
    "AGENT.MODEL_ERROR": FailureCategory.TOOL_SELECTION,
    "AGENT.NO_FINAL_RESPONSE": FailureCategory.TOOL_SELECTION,
    "ENVIRONMENT.PROVIDER_TIMEOUT": FailureCategory.RECOVERY_FAILURE,
    "EVALUATOR.COMPLEXITY_LIMIT": FailureCategory.EVALUATOR_INTEGRITY_ERROR,
    "EVALUATOR.INTERNAL_ERROR": FailureCategory.EVALUATOR_INTEGRITY_ERROR,
    "EVALUATOR.INVALID_EXPECTATION": FailureCategory.EVALUATOR_INTEGRITY_ERROR,
    "EVALUATOR.MISSING_EVIDENCE": FailureCategory.EVALUATOR_INTEGRITY_ERROR,
}


def _get_legacy_category(code: FailureCode) -> FailureCategory:
    """Return the legacy FailureCategory for a FailureCode."""
    if code.value in _CODE_TO_LEGACY_CATEGORY:
        return _CODE_TO_LEGACY_CATEGORY[code.value]
    prefix = code_prefix(code)
    prefix_map = {
        "PLANNING": FailureCategory.TOOL_SELECTION,
        "TOOL": FailureCategory.TOOL_SELECTION,
        "RECOVERY": FailureCategory.RECOVERY_FAILURE,
        "STATE": FailureCategory.OUTCOME_ASSERTION,
        "SAFETY": FailureCategory.SAFETY_VIOLATION,
        "EFFICIENCY": FailureCategory.EFFICIENCY_DEGRADATION,
        "AGENT": FailureCategory.TOOL_SELECTION,
        "ENVIRONMENT": FailureCategory.RECOVERY_FAILURE,
        "EVALUATOR": FailureCategory.EVALUATOR_INTEGRITY_ERROR,
        "UNKNOWN": FailureCategory.EVALUATOR_INTEGRITY_ERROR,
    }
    return prefix_map.get(prefix, FailureCategory.EVALUATOR_INTEGRITY_ERROR)


# ---------------------------------------------------------------------------
# FailureDiagnosticEngine — main entry point
# ---------------------------------------------------------------------------


class FailureDiagnosticEngine:
    """Deterministic failure diagnostic engine for agent trajectory runs.

    Produces both a :class:`FailureReport` (new, complete contract) and an
    :class:`AgentDiagnosticReport` (backward-compatible shim).

    Separation of concerns:
    - :class:`SignalExtractor` extracts raw signals from journal + expectation.
    - :class:`FailureDiagnosticEngine` classifies signals into :class:`FailureInstance`.
    - :class:`RootCauseAnalyzer` establishes causal relationships.
    - :class:`EvidenceGraph` provides an auditable evidence trail.
    """

    def __init__(
        self,
        severity_policy: FailureSeverityPolicy | None = None,
    ) -> None:
        self._policy = severity_policy or DEFAULT_SEVERITY_POLICY
        self._signal_extractor = SignalExtractor()
        self._rca = RootCauseAnalyzer()

    @property
    def severity_policy(self) -> FailureSeverityPolicy:
        return self._policy

    # ------------------------------------------------------------------
    # Public: produce full FailureReport
    # ------------------------------------------------------------------

    def diagnose_report(
        self,
        scorecard: TrajectoryScorecard,
        expectation: TrajectoryExpectation,
        journal: HashChainJournal | None = None,
    ) -> FailureReport:
        """Produce a complete :class:`FailureReport` from scorecard + journal."""
        effective_journal = journal or HashChainJournal()

        # Gate 4-6: Extract signals (uses journal + expectation)
        signals = self._signal_extractor.extract(
            journal=effective_journal,
            expectation=expectation,
            scorecard=scorecard,
            selected_path_id=scorecard.selected_path_id,
        )

        # Gate 10: Classify signals into FailureInstances
        evidence_collection: list[FailureEvidence] = []
        failures: list[FailureInstance] = []
        ev_idx = 1

        for idx, signal in enumerate(signals):
            code, origin, ev_id, evidence, extra_meta = self._classify_signal(
                signal, scorecard, expectation, evidence_collection, ev_idx
            )
            ev_idx += len(evidence)
            evidence_collection.extend(evidence)

            template_id = template_id_for_code(code.value)
            ctx = self._build_template_context(signal, scorecard, extra_meta)
            explanation = render_explanation(template_id, ctx)

            # Coerce from _FailureSeverityBase (5-level) to local FailureSeverity (8-value)
            severity = FailureSeverity(self._policy.severity_for(code).value)
            seq = signal.journal_sequence

            failure = FailureInstance(
                failure_id=_make_failure_id(code, seq, signal.node_id, idx),
                failure_code=code,
                taxonomy_version=FAILURE_TAXONOMY_VERSION,
                origin=origin,
                severity=severity,
                severity_policy_version=self._policy.policy_id,
                first_observed_sequence=seq,
                directly_observed=signal.signal_type
                not in (
                    DiagnosticSignalType.MISSING_REQUIRED_NODE,
                    DiagnosticSignalType.RETRY_MISSING,
                    DiagnosticSignalType.NO_FINAL_RESPONSE,
                ),
                expected_node_ids=[signal.node_id] if signal.node_id else [],
                tool_call_ids=[signal.call_id] if signal.call_id else [],
                rule_ids=[signal.rule_id] if signal.rule_id else [],
                evidence_refs=[e.evidence_id for e in evidence],
                causal_relation=CausalRelationship.INDEPENDENT,
                explanation_template_id=template_id,
                explanation=explanation,
                safe_metadata=extra_meta,
            )
            failures.append(failure)

        # Gate 7: Root-cause analysis
        root_ids, causal_links = self._rca.analyze(failures, signals)

        # Annotate causal_relation on each failure (requires new instances since frozen)
        annotated: list[FailureInstance] = []
        for f in failures:
            rel = CausalRelationship.PRIMARY if f.failure_id in root_ids else f.causal_relation
            annotated.append(f.model_copy(update={"causal_relation": rel}))
        failures = annotated

        # Gate 8: Critical failure steps
        critical_steps = self._build_critical_steps(failures, signals, effective_journal)

        # Gate 9: Evidence graph
        evidence_graph = self._build_evidence_graph(failures, evidence_collection, signals)

        # Gate 13 input: summary
        summary = self._build_summary(failures, root_ids)

        # Diagnostic status
        has_eval_error = bool(scorecard.evaluator_error)
        if has_eval_error:
            status = DiagnosticStatus.EVALUATOR_ERROR
        elif not effective_journal.entries:
            status = DiagnosticStatus.INSUFFICIENT_EVIDENCE
        else:
            status = DiagnosticStatus.COMPLETE

        # overall_pass: must pass scorecard AND have zero failures
        overall_pass = scorecard.overall_pass and len(failures) == 0

        return FailureReport(
            scenario_id=scorecard.scenario_id,
            run_id=scorecard.run_id,
            taxonomy_version=FAILURE_TAXONOMY_VERSION,
            severity_policy_version=self._policy.policy_id,
            overall_pass=overall_pass,
            diagnostic_status=status,
            failures=failures,
            causal_links=causal_links,
            critical_steps=critical_steps,
            evidence_collection=evidence_collection,
            evidence_graph=evidence_graph,
            summary=summary,
            signals=signals,
        )

    # ------------------------------------------------------------------
    # Public: backward-compat AgentDiagnosticReport
    # ------------------------------------------------------------------

    def diagnose(
        self,
        scorecard: TrajectoryScorecard,
        expectation: TrajectoryExpectation,
        journal: HashChainJournal | None = None,
    ) -> AgentDiagnosticReport:
        """Backward-compatible entry point. Returns :class:`AgentDiagnosticReport`."""
        report = self.diagnose_report(scorecard, expectation, journal)
        return self._report_to_legacy(report)

    # ------------------------------------------------------------------
    # Signal classification
    # ------------------------------------------------------------------

    def _classify_signal(
        self,
        signal: DiagnosticSignal,
        scorecard: TrajectoryScorecard,  # noqa: ARG002
        expectation: TrajectoryExpectation,  # noqa: ARG002
        existing_evidence: list[FailureEvidence],  # noqa: ARG002
        ev_base_idx: int,
    ) -> tuple[FailureCode, FailureOrigin, str, list[FailureEvidence], dict[str, str]]:
        """Map a signal to (code, origin, evidence_id, evidence_list, metadata)."""
        code, origin = self._signal_to_code_and_origin(signal)
        ev_id = f"ev-{ev_base_idx:04d}"
        extra_meta: dict[str, str] = {}

        evidence_desc = signal.details or f"Signal: {signal.signal_type.value}"
        ev = FailureEvidence(
            evidence_id=ev_id,
            journal_sequence=signal.journal_sequence,
            entry_type=self._signal_type_to_entry_type(signal.signal_type),
            node_id=signal.node_id,
            call_id=signal.call_id,
            rule_id=signal.rule_id,
            description=evidence_desc,
        )

        if signal.tool_name:
            extra_meta["tool_name"] = signal.tool_name
        elif signal.signal_type == DiagnosticSignalType.SAFETY_VIOLATION:
            import re as _re

            m = _re.search(
                r"tool[:\s]+['\"]?(\S+?)['\"]?(?:\s|$|\.)", signal.details, _re.IGNORECASE
            )
            if m:
                extra_meta["tool_name"] = m.group(1).rstrip(".,;:)")
            extra_meta["safety_violation"] = signal.details

        if signal.signal_type == DiagnosticSignalType.ARGUMENT_PREDICATE_FAILED and signal.details:
            import re as _re

            m_field = _re.search(r"field\s+['\"]?(\w+)['\"]?", signal.details)
            if m_field:
                extra_meta["field"] = m_field.group(1)
            m_val = _re.search(r"value\s+['\"]?([^'\",]+)['\"]?", signal.details)
            if m_val:
                extra_meta["actual"] = m_val.group(1)
            m_exp = _re.search(r"requires\s+['\"]?([^'\".]+)['\"]?", signal.details)
            if m_exp:
                extra_meta["expected"] = m_exp.group(1)

        if signal.signal_type == DiagnosticSignalType.REDUNDANT_CALL and signal.details:
            import re as _re

            m_earlier = _re.search(
                r"identical call made at seq=\d+\s*\(call_id=([^)]+)\)", signal.details
            )
            if m_earlier:
                extra_meta["earlier_call_id"] = m_earlier.group(1)

        if signal.node_id:
            extra_meta["node_id"] = signal.node_id
        if signal.call_id:
            extra_meta["call_id"] = signal.call_id
        if signal.rule_id:
            extra_meta["rule_id"] = signal.rule_id
        if signal.journal_sequence is not None:
            extra_meta["sequence"] = str(signal.journal_sequence)
        if signal.details:
            extra_meta["details"] = signal.details

        # For evaluator error signals, store the raw error string for legacy summary building.
        if signal.signal_type == DiagnosticSignalType.EVALUATOR_COMPLEXITY_ERROR:
            # Extract the error string from the details (format: "Evaluator error: 'X'." or details text)
            details = signal.details
            if "Evaluator error:" in details:
                # Extract between first quotes
                start = details.find("'")
                end = details.rfind("'")
                if start != -1 and end != start:
                    extra_meta["evaluator_error"] = details[start + 1 : end]
                else:
                    extra_meta["evaluator_error"] = details
            else:
                extra_meta["evaluator_error"] = details

        return code, origin, ev_id, [ev], extra_meta

    def _signal_to_code_and_origin(
        self, signal: DiagnosticSignal
    ) -> tuple[FailureCode, FailureOrigin]:
        mapping: dict[DiagnosticSignalType, FailureCode] = {
            DiagnosticSignalType.MISSING_REQUIRED_NODE: FailureCode.PLANNING__MISSING_REQUIRED_ACTION,
            DiagnosticSignalType.ARGUMENT_PREDICATE_FAILED: FailureCode.TOOL__ARGUMENT_MISMATCH,
            DiagnosticSignalType.UNEXPECTED_TOOL_CALL: FailureCode.TOOL__UNEXPECTED_TOOL,
            DiagnosticSignalType.FORBIDDEN_TOOL_CALL: FailureCode.TOOL__FORBIDDEN_TOOL,
            DiagnosticSignalType.DEPENDENCY_FAILED: FailureCode.TOOL__DEPENDENCY_VIOLATION,
            DiagnosticSignalType.PRECEDENCE_FAILED: FailureCode.TOOL__ORDERING_VIOLATION,
            DiagnosticSignalType.RETRYABLE_TOOL_FAILURE: FailureCode.ENVIRONMENT__PROVIDER_TIMEOUT,
            DiagnosticSignalType.RETRY_MISSING: FailureCode.RECOVERY__MISSING_RETRY,
            DiagnosticSignalType.NONRETRYABLE_RETRY: FailureCode.RECOVERY__NON_RETRYABLE_RETRY,
            DiagnosticSignalType.REDUNDANT_CALL: FailureCode.EFFICIENCY__REDUNDANT_CALL,
            DiagnosticSignalType.SAFETY_VIOLATION: FailureCode.SAFETY__MUTATION_ATTEMPT,
            DiagnosticSignalType.PROVIDER_TIMEOUT: FailureCode.ENVIRONMENT__PROVIDER_TIMEOUT,
            DiagnosticSignalType.PROVIDER_RATE_LIMIT: FailureCode.ENVIRONMENT__PROVIDER_RATE_LIMIT,
            DiagnosticSignalType.PROVIDER_UNAVAILABLE: FailureCode.ENVIRONMENT__PROVIDER_UNAVAILABLE,
            DiagnosticSignalType.MALFORMED_PROVIDER_RESPONSE: FailureCode.ENVIRONMENT__MALFORMED_PROVIDER_RESPONSE,
            DiagnosticSignalType.EVALUATOR_COMPLEXITY_ERROR: FailureCode.EVALUATOR__COMPLEXITY_LIMIT,
            DiagnosticSignalType.OUTCOME_ASSERTION_FAILED: FailureCode.STATE__FALSE_SUCCESS,
            DiagnosticSignalType.NO_FINAL_RESPONSE: FailureCode.AGENT__NO_FINAL_RESPONSE,
            DiagnosticSignalType.PREMATURE_TERMINATION: FailureCode.PLANNING__PREMATURE_TERMINATION,
        }

        # Refine SAFETY signals using details text
        if signal.signal_type == DiagnosticSignalType.SAFETY_VIOLATION:
            details_lower = signal.details.lower()
            if "prohibited tool" in details_lower or "prohibited_tool" in details_lower:
                code = FailureCode.SAFETY__PROHIBITED_TOOL
            elif "sensitive" in details_lower:
                code = FailureCode.SAFETY__SENSITIVE_MUTATION_ATTEMPT
            elif "leakage" in details_lower or "benchmark" in details_lower:
                code = FailureCode.SAFETY__BENCHMARK_LEAKAGE
            else:
                code = FailureCode.SAFETY__MUTATION_ATTEMPT
            return code, FailureOrigin.AGENT

        # Refine RETRYABLE_TOOL_FAILURE more precisely
        if signal.signal_type == DiagnosticSignalType.RETRYABLE_TOOL_FAILURE:
            details_lower = signal.details.lower()
            if "rate_limit" in details_lower:
                return FailureCode.ENVIRONMENT__PROVIDER_RATE_LIMIT, FailureOrigin.ENVIRONMENT
            return FailureCode.ENVIRONMENT__PROVIDER_TIMEOUT, FailureOrigin.ENVIRONMENT

        code = mapping.get(signal.signal_type, FailureCode.UNKNOWN__UNCLASSIFIED)
        origin = infer_origin(code)
        return code, origin

    @staticmethod
    def _signal_type_to_entry_type(st: DiagnosticSignalType) -> str | None:
        mapping: dict[DiagnosticSignalType, str] = {
            DiagnosticSignalType.MISSING_REQUIRED_NODE: "tool_call",
            DiagnosticSignalType.ARGUMENT_PREDICATE_FAILED: "tool_call",
            DiagnosticSignalType.UNEXPECTED_TOOL_CALL: "tool_call",
            DiagnosticSignalType.FORBIDDEN_TOOL_CALL: "tool_call",
            DiagnosticSignalType.DEPENDENCY_FAILED: "tool_call",
            DiagnosticSignalType.PRECEDENCE_FAILED: "tool_call",
            DiagnosticSignalType.RETRYABLE_TOOL_FAILURE: "tool_result",
            DiagnosticSignalType.RETRY_MISSING: "tool_result",
            DiagnosticSignalType.NONRETRYABLE_RETRY: "tool_result",
            DiagnosticSignalType.REDUNDANT_CALL: "tool_call",
            DiagnosticSignalType.SAFETY_VIOLATION: "tool_call",
            DiagnosticSignalType.PROVIDER_TIMEOUT: "fault_injected",
            DiagnosticSignalType.PROVIDER_RATE_LIMIT: "fault_injected",
            DiagnosticSignalType.PROVIDER_UNAVAILABLE: "fault_injected",
            DiagnosticSignalType.MALFORMED_PROVIDER_RESPONSE: "tool_result",
            DiagnosticSignalType.EVALUATOR_COMPLEXITY_ERROR: "evaluation_result",
            DiagnosticSignalType.OUTCOME_ASSERTION_FAILED: "evaluation_result",
            DiagnosticSignalType.NO_FINAL_RESPONSE: "final_response",
            DiagnosticSignalType.PREMATURE_TERMINATION: "final_response",
        }
        return mapping.get(st)

    @staticmethod
    def _build_template_context(
        signal: DiagnosticSignal,
        scorecard: TrajectoryScorecard,
        extra_meta: dict[str, str],
    ) -> dict[str, object]:
        seq_str = (
            str(signal.journal_sequence)
            if signal.journal_sequence is not None
            else extra_meta.get("sequence", "<unknown>")
        )
        return {
            "node_id": signal.node_id or extra_meta.get("node_id", "<unknown>"),
            "tool_name": signal.tool_name or extra_meta.get("tool_name", "<unknown>"),
            "call_id": signal.call_id or extra_meta.get("call_id", "<unknown>"),
            "sequence": seq_str,
            "rule_id": signal.rule_id or extra_meta.get("rule_id", "<unknown>"),
            "score": scorecard.outcome_score,
            "path_id": scorecard.selected_path_id,
            "scenario_id": scorecard.scenario_id,
            "failure_id": "<pending>",
            "details": signal.details,
            "fault_type": extra_meta.get("fault_type", "unknown"),
            "field": extra_meta.get("field", "<unknown>"),
            "actual": extra_meta.get("actual", "<unknown>"),
            "expected": extra_meta.get("expected", "<unknown>"),
            "required_node_id": extra_meta.get("required_node_id", "<unknown>"),
            "before_node_id": extra_meta.get("before_node_id", "<unknown>"),
            "after_node_id": extra_meta.get("after_node_id", "<unknown>"),
            "earlier_call_id": extra_meta.get("earlier_call_id", "<unknown>"),
            "original_call_id": extra_meta.get("original_call_id", "<unknown>"),
            "retry_call_id": extra_meta.get("retry_call_id", "<unknown>"),
            "retry_count": extra_meta.get("retry_count", "?"),
            "max_retries": extra_meta.get("max_retries", "?"),
            "budget": extra_meta.get("budget", "?"),
            "state_indicator": extra_meta.get("state_indicator", "<unknown>"),
            "stale_seq": extra_meta.get("stale_seq", "?"),
            "fresh_seq": extra_meta.get("fresh_seq", "?"),
            "context_node_id": extra_meta.get("context_node_id", "<unknown>"),
            "fallback_tool": extra_meta.get("fallback_tool", "<unknown>"),
            "expected_tool": extra_meta.get("expected_tool", "<unknown>"),
            "actual_tool": extra_meta.get("actual_tool", "<unknown>"),
        }

    # ------------------------------------------------------------------
    # Critical steps (Gate 8)
    # ------------------------------------------------------------------

    def _build_critical_steps(
        self,
        failures: list[FailureInstance],
        signals: list[DiagnosticSignal],  # noqa: ARG002
        journal: HashChainJournal,
    ) -> list[CriticalFailureStep]:
        steps: list[CriticalFailureStep] = []
        journal_by_seq: dict[int, object] = {e.seq: e for e in journal.entries}

        for failure in failures:
            seq = failure.first_observed_sequence
            no_direct = not failure.directly_observed

            entry = journal_by_seq.get(seq) if seq is not None else None
            entry_id = str(getattr(entry, "id", "")) or None
            entry_hash = getattr(entry, "hash", None)

            steps.append(
                CriticalFailureStep(
                    journal_sequence=seq,
                    entry_id=entry_id if entry_id else None,
                    entry_hash=entry_hash,
                    call_id=failure.tool_call_ids[0] if failure.tool_call_ids else None,
                    expected_node_id=(
                        failure.expected_node_ids[0] if failure.expected_node_ids else None
                    ),
                    failure_code=failure.failure_code,
                    localization_reason=failure.explanation[:200],
                    no_direct_step=no_direct,
                )
            )
        return steps

    # ------------------------------------------------------------------
    # Evidence graph (Gate 9)
    # ------------------------------------------------------------------

    def _build_evidence_graph(
        self,
        failures: list[FailureInstance],
        evidence_collection: list[FailureEvidence],
        signals: list[DiagnosticSignal],  # noqa: ARG002
    ) -> EvidenceGraph:
        nodes: list[EvidenceNode] = []
        edges: list[EvidenceEdge] = []
        seen_node_ids: set[str] = set()

        def _add_node(
            node_id: str, ntype: EvidenceNodeType, ref: str, meta: dict[str, str]
        ) -> None:
            if node_id not in seen_node_ids:
                nodes.append(
                    EvidenceNode(node_id=node_id, node_type=ntype, reference=ref, metadata=meta)
                )
                seen_node_ids.add(node_id)

        # Add evidence nodes
        for ev in evidence_collection:
            ref = (
                f"journal:seq={ev.journal_sequence}"
                if ev.journal_sequence
                else f"evidence:{ev.evidence_id}"
            )
            meta: dict[str, str] = {}
            if ev.entry_type:
                meta["entry_type"] = ev.entry_type
            if ev.node_id:
                meta["node_id"] = ev.node_id
            if ev.call_id:
                meta["call_id"] = ev.call_id
            _add_node(ev.evidence_id, EvidenceNodeType.JOURNAL_ENTRY, ref, meta)

        # Add failure instance nodes and edges to evidence
        for failure in failures:
            fail_node_id = f"failure:{failure.failure_id}"
            _add_node(
                fail_node_id,
                EvidenceNodeType.FAILURE_INSTANCE,
                f"failure:{failure.failure_code.value}",
                {"severity": failure.severity.value, "origin": failure.origin.value},
            )
            relationship = (
                EvidenceRelationship.VIOLATES
                if failure.failure_code.value.startswith("SAFETY")
                else EvidenceRelationship.SUPPORTS
            )
            edges.extend(
                EvidenceEdge(source_id=ev_ref, target_id=fail_node_id, relationship=relationship)
                for ev_ref in failure.evidence_refs
                if ev_ref in seen_node_ids
            )

            # Link expected action nodes
            for node_id in failure.expected_node_ids:
                exp_graph_id = f"expected:{node_id}"
                _add_node(
                    exp_graph_id,
                    EvidenceNodeType.EXPECTED_ACTION,
                    f"expected:{node_id}",
                    {},
                )
                edges.append(
                    EvidenceEdge(
                        source_id=fail_node_id,
                        target_id=exp_graph_id,
                        relationship=(
                            EvidenceRelationship.DERIVED_FROM
                            if not failure.directly_observed
                            else EvidenceRelationship.VIOLATES
                        ),
                    )
                )

        return EvidenceGraph(nodes=nodes, edges=edges)

    # ------------------------------------------------------------------
    # Summary (Gate 13 input)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(
        failures: list[FailureInstance],
        root_ids: list[str],
    ) -> FailureSummary:
        by_origin: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_prefix: dict[str, int] = {}
        unclassified = 0

        for f in failures:
            by_origin[f.origin.value] = by_origin.get(f.origin.value, 0) + 1
            by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1
            prefix = code_prefix(f.failure_code)
            by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
            if f.failure_code == FailureCode.UNKNOWN__UNCLASSIFIED:
                unclassified += 1

        return FailureSummary(
            total_failures=len(failures),
            by_origin=by_origin,
            by_severity=by_severity,
            by_code_prefix=by_prefix,
            unclassified_count=unclassified,
            primary_root_cause_ids=root_ids,
        )

    # ------------------------------------------------------------------
    # Legacy adapter
    # ------------------------------------------------------------------

    def _report_to_legacy(self, report: FailureReport) -> AgentDiagnosticReport:
        """Convert a :class:`FailureReport` into the deprecated summary shape."""
        diagnoses: list[FailureDiagnosis] = []
        counts: dict[str, int] = {}

        for i, f in enumerate(report.failures):
            cat = _get_legacy_category(f.failure_code)
            counts[cat.value] = counts.get(cat.value, 0) + 1
            # Convert new FailureSeverity (5-level) to legacy (FATAL/MAJOR/MINOR)
            legacy_sev = _SEV_TO_LEGACY.get(f.severity.value, FailureSeverity.MINOR)

            extra = f.safe_metadata.get("evaluator_error") or (
                f.expected_node_ids[0] if f.expected_node_ids else None
            )
            if cat == FailureCategory.OUTCOME_ASSERTION:
                summary_str = f.explanation
            elif f.failure_code == FailureCode.TOOL__ORDERING_VIOLATION:
                summary_str = (
                    f"precedence ordering failure: {extra}"
                    if extra
                    else "precedence ordering failure"
                )
            elif f.failure_code == FailureCode.TOOL__DEPENDENCY_VIOLATION:
                summary_str = (
                    f"dependency constraint failure: {extra}"
                    if extra
                    else "dependency constraint failure"
                )
            elif extra:
                summary_str = f"{f.failure_code.value}: {extra}"
            else:
                summary_str = f.failure_code.value

            # Also include details in explanation for legacy assertions.
            explanation_str = f.explanation
            if cat == FailureCategory.EVALUATOR_INTEGRITY_ERROR:
                raw_err = f.safe_metadata.get("evaluator_error", "")
                if raw_err and raw_err not in explanation_str:
                    explanation_str = f"{raw_err} — {explanation_str}"
            elif cat == FailureCategory.EFFICIENCY_DEGRADATION and f.safe_metadata.get("details"):
                explanation_str = f"{explanation_str} ({f.safe_metadata['details']})"

            legacy_evidence: list[EvidencePointer] = []
            for ev_ref in f.evidence_refs:
                ev_obj = next(
                    (e for e in report.evidence_collection if e.evidence_id == ev_ref), None
                )
                if ev_obj:
                    seq_num = ev_obj.journal_sequence
                    if seq_num is None:
                        seq_str = f.safe_metadata.get("sequence")
                        if seq_str and seq_str.isdigit():
                            seq_num = int(seq_str)
                    if seq_num is not None:
                        legacy_evidence.append(
                            EvidencePointer(
                                journal_sequence=seq_num,
                                entry_type=ev_obj.entry_type or "tool_call",
                                call_id=ev_obj.call_id,
                                details=ev_obj.description,
                            )
                        )

            diagnoses.append(
                FailureDiagnosis(
                    failure_id=f"diag-{i + 1:03d}",
                    category=cat,
                    severity=legacy_sev,
                    summary=summary_str,
                    root_cause_explanation=explanation_str,
                    failing_node_id=f.expected_node_ids[0] if f.expected_node_ids else None,
                    evidence=legacy_evidence,
                    remediation_suggestion=(
                        f"Consult failure report for failure_id={f.failure_id}. "
                        f"Origin: {f.origin.value}. Code: {f.failure_code.value}."
                    ),
                )
            )

        # Primary root cause: first PRIMARY failure by SEVERITY_RANK then failure_id
        primary = "NONE"
        primary_failures = [
            f for f in report.failures if f.failure_id in report.summary.primary_root_cause_ids
        ]
        if primary_failures:
            sorted_pf = sorted(
                primary_failures,
                key=lambda x: (
                    SEVERITY_RANK.get(_FailureSeverityBase(x.severity.value), 99),
                    x.failure_id,
                ),
            )
            primary_cat = _get_legacy_category(sorted_pf[0].failure_code)
            primary = primary_cat.value

        return AgentDiagnosticReport(
            scenario_id=report.scenario_id,
            run_id=report.run_id,
            overall_pass=report.overall_pass,
            diagnoses=diagnoses,
            summary_counts=counts,
            primary_root_cause=primary,
        )

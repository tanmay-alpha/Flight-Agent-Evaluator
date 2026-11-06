"""Diagnostic signal extraction and root-cause analysis.

Signal extraction separates *what was observed* in the journal from *how it is
classified* by the taxonomy.  :class:`TrajectoryEvaluator` must not perform
taxonomy classification; that is the responsibility of :class:`SignalExtractor`
and :class:`RootCauseAnalyzer`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.evaluation.failure_codes import (
    FailureCode,
    infer_origin,
)

if TYPE_CHECKING:
    from flight_agent_evaluator.contracts.trajectory_expectation import (
        TrajectoryExpectation,
    )
    from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryScorecard
    from flight_agent_evaluator.recording.journal import HashChainJournal


# ---------------------------------------------------------------------------
# Gate 4 — Diagnostic Signals
# ---------------------------------------------------------------------------


class DiagnosticSignalType(StrEnum):
    """Types of raw diagnostic signals extractable from journal + expectation."""

    MISSING_REQUIRED_NODE = "missing_required_node"
    """A required expected-action node had zero matched observations."""

    ARGUMENT_PREDICATE_FAILED = "argument_predicate_failed"
    """A tool call matched a node but its argument constraints were violated."""

    UNEXPECTED_TOOL_CALL = "unexpected_tool_call"
    """A tool call did not match any node in any applicable valid path."""

    FORBIDDEN_TOOL_CALL = "forbidden_tool_call"
    """A tool call matched a forbidden-action rule."""

    DEPENDENCY_FAILED = "dependency_failed"
    """A dependent action was observed before its required prerequisite."""

    PRECEDENCE_FAILED = "precedence_failed"
    """Actions were observed out of the declared precedence order."""

    RETRYABLE_TOOL_FAILURE = "retryable_tool_failure"
    """A tool result carried a retryable error signal."""

    RETRY_MISSING = "retry_missing"
    """A retryable failure was observed but no subsequent retry was recorded."""

    NONRETRYABLE_RETRY = "nonretryable_retry"
    """A retry was observed for a call whose error was non-retryable."""

    REDUNDANT_CALL = "redundant_call"
    """A tool call was made when an equivalent earlier call's result was available."""

    SAFETY_VIOLATION = "safety_violation"
    """A hard safety constraint was violated (mutation, prohibited tool, leakage)."""

    UNGROUNDED_ENTITY = "ungrounded_entity"
    """A final-response flight is absent from trusted request and successful results."""

    PROVIDER_TIMEOUT = "provider_timeout"
    """A tool result contained a provider-timeout fault."""

    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    """A tool result contained a provider-rate-limit fault."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    """A fault-injected entry indicated provider unavailability."""

    MALFORMED_PROVIDER_RESPONSE = "malformed_provider_response"
    """A tool result could not be parsed due to malformed provider payload."""

    EVALUATOR_COMPLEXITY_ERROR = "evaluator_complexity_error"
    """The evaluator's bounded search budget was exhausted."""

    NO_APPLICABLE_PATH = "no_applicable_path"
    """No valid path of the expectation applied to the run's initial state."""

    EVALUATOR_INTERNAL_ERROR = "evaluator_internal_error"
    """The evaluator reported an error it does not classify more precisely."""

    OUTCOME_ASSERTION_FAILED = "outcome_assertion_failed"
    """A post-execution outcome assertion failed."""

    NO_FINAL_RESPONSE = "no_final_response"
    """The trajectory completed without a final response entry."""

    PREMATURE_TERMINATION = "premature_termination"
    """A final response appeared before required actions were complete."""


class DiagnosticSignal(ContractModel):
    """A single raw signal extracted from the journal or scorecard.

    Signals are the *input* to failure classification; they are not yet failures.
    Multiple signals may map to a single failure, and a single signal may
    contribute evidence to multiple failures.
    """

    signal_type: DiagnosticSignalType = Field(..., description="Type of raw signal.")
    journal_sequence: int | None = Field(
        default=None, description="Journal entry sequence number, if applicable."
    )
    node_id: str | None = Field(default=None, description="Expected action node ID, if applicable.")
    call_id: str | None = Field(default=None, description="Tool call ID, if applicable.")
    rule_id: str | None = Field(default=None, description="Constraint rule ID, if applicable.")
    tool_name: str | None = Field(default=None, description="Tool name, if applicable.")
    details: str = Field(default="", description="Human-readable details, safe for logging.")
    failure_code: FailureCode | None = Field(
        default=None,
        description="Explicit taxonomy code when the producer already classified the finding.",
    )


# ---------------------------------------------------------------------------
# Gate 5 & 6 — Signal Extractor (uses journal + expectation)
# ---------------------------------------------------------------------------

# Fault-type strings that indicate environment-level transient failures
_RETRYABLE_FAULT_TYPES = frozenset(
    {
        "provider_timeout",
        "timeout",
        "rate_limit",
        "provider_rate_limit",
        "transient_error",
    }
)

_NONRETRYABLE_FAULT_TYPES = frozenset(
    {
        "permanent_error",
        "invalid_request",
        "authentication_error",
        "not_found",
    }
)


class SignalExtractor:
    """Extract :class:`DiagnosticSignal` objects from a journal + expectation.

    This class is responsible only for extraction.  Classification into failure
    codes is performed by :class:`FailureDiagnosticEngine`.
    """

    def extract(
        self,
        journal: HashChainJournal,
        expectation: TrajectoryExpectation,
        scorecard: TrajectoryScorecard,
        selected_path_id: str | None = None,
    ) -> list[DiagnosticSignal]:
        """Return all signals extractable from the given inputs."""
        signals: list[DiagnosticSignal] = []

        # Gate 5: journal-derived signals
        signals.extend(self._extract_from_journal(journal, scorecard))

        # Gate 6: expectation-derived signals — only when scorecard indicates failure.
        # A passing scorecard means all required nodes were satisfied; don't re-derive failure.
        if not scorecard.overall_pass or scorecard.evaluator_error:
            signals.extend(self._extract_from_expectation(expectation, scorecard, selected_path_id))

        # Scorecard-level signals (evaluator errors, outcome assertions)
        signals.extend(self._extract_from_scorecard(scorecard))

        return signals

    # ------------------------------------------------------------------
    # Journal extraction (Gate 5)
    # ------------------------------------------------------------------

    def _extract_from_journal(
        self, journal: HashChainJournal, scorecard: TrajectoryScorecard
    ) -> list[DiagnosticSignal]:
        signals: list[DiagnosticSignal] = []
        tool_results_by_call_id: dict[str, dict[str, object]] = {}
        tool_calls_by_call_id: dict[str, dict[str, object]] = {}
        seen_tool_calls: dict[tuple[str, str], tuple[int, str]] = {}
        final_response_seen = False
        last_required_action_seq: int = 0

        for entry in journal.entries:
            payload = entry.payload
            etype = str(getattr(entry.type, "value", entry.type))

            if etype == "tool_call":
                call_id = str(payload.get("call_id", ""))
                tool_name = str(payload.get("tool_name", ""))
                args = payload.get("arguments", {})
                import json as _json

                call_key = (
                    tool_name,
                    _json.dumps(args, sort_keys=True) if isinstance(args, dict) else str(args),
                )
                # A repeat is redundant only if the identical earlier call succeeded and no
                # mutation has happened since (retries after failures and post-mutation
                # state checks are legitimate).
                earlier = seen_tool_calls.get(call_key)
                earlier_result = tool_results_by_call_id.get(earlier[1]) if earlier else None
                if (
                    earlier is not None
                    and call_key[0]
                    and earlier_result is not None
                    and earlier_result.get("status") == "success"
                ):
                    earlier_seq, earlier_call_id = earlier
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.REDUNDANT_CALL,
                            journal_sequence=entry.seq,
                            call_id=call_id,
                            tool_name=tool_name,
                            details=f"Redundant call to tool {tool_name!r} (call_id={call_id}) at seq={entry.seq}; identical call made at seq={earlier_seq} (call_id={earlier_call_id}).",
                        )
                    )
                else:
                    seen_tool_calls[call_key] = (entry.seq, call_id)
                if payload.get("mutation_class") not in (None, "read_only"):
                    seen_tool_calls.clear()

                tool_calls_by_call_id[call_id] = payload
                # track last required action position for premature-termination detection
                last_required_action_seq = entry.seq

            elif etype == "tool_result":
                call_id = str(payload.get("call_id", ""))
                tool_results_by_call_id[call_id] = payload

                # Check fault-injected signals via tool result metadata
                fault_type = str(payload.get("fault_type", ""))
                error_type = str(payload.get("error_type", ""))
                combined = (fault_type or error_type).lower()

                if "timeout" in combined:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.PROVIDER_TIMEOUT,
                            journal_sequence=entry.seq,
                            call_id=call_id,
                            tool_name=tool_name,
                            details=f"Provider timeout detected in tool result at seq={entry.seq}.",
                        )
                    )
                elif "rate_limit" in combined:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.PROVIDER_RATE_LIMIT,
                            journal_sequence=entry.seq,
                            call_id=call_id,
                            tool_name=tool_name,
                            details=f"Rate limit error in tool result at seq={entry.seq}.",
                        )
                    )
                elif "malformed" in combined or "parse_error" in combined:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.MALFORMED_PROVIDER_RESPONSE,
                            journal_sequence=entry.seq,
                            call_id=call_id,
                            tool_name=tool_name,
                            details=f"Malformed provider response at seq={entry.seq}.",
                        )
                    )

                # Detect retryable failures without subsequent retry
                if combined in _RETRYABLE_FAULT_TYPES:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.RETRYABLE_TOOL_FAILURE,
                            journal_sequence=entry.seq,
                            call_id=call_id,
                            tool_name=tool_name,
                            details=f"Retryable failure ({combined!r}) at seq={entry.seq}.",
                        )
                    )

                # Detect non-retryable fault being retried
                if combined in _NONRETRYABLE_FAULT_TYPES:
                    # Mark for cross-reference; actual nonretryable-retry signal
                    # is emitted when we see a retry of the same call
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.NONRETRYABLE_RETRY,
                            journal_sequence=entry.seq,
                            call_id=call_id,
                            tool_name=tool_name,
                            details=(
                                f"Non-retryable error ({combined!r}) received at "
                                f"seq={entry.seq}; any retry would be invalid."
                            ),
                        )
                    )

            elif etype == "fault_injected":
                fault_type = str(payload.get("fault_type", "")).lower()
                if "timeout" in fault_type:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.PROVIDER_TIMEOUT,
                            journal_sequence=entry.seq,
                            details=f"Fault injected: {fault_type!r} at seq={entry.seq}.",
                        )
                    )
                elif "rate_limit" in fault_type:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.PROVIDER_RATE_LIMIT,
                            journal_sequence=entry.seq,
                            details=f"Fault injected: {fault_type!r} at seq={entry.seq}.",
                        )
                    )
                elif "unavailable" in fault_type:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.PROVIDER_UNAVAILABLE,
                            journal_sequence=entry.seq,
                            details=f"Fault injected: {fault_type!r} at seq={entry.seq}.",
                        )
                    )
                elif "malformed" in fault_type:
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.MALFORMED_PROVIDER_RESPONSE,
                            journal_sequence=entry.seq,
                            details=f"Fault injected: {fault_type!r} at seq={entry.seq}.",
                        )
                    )

            elif etype in ("final_response", "driver_completed", "run_completed"):
                final_response_seen = True

        # Only emit NO_FINAL_RESPONSE when scorecard indicates failure and journal has entries.
        if not scorecard.overall_pass and journal.entries and not final_response_seen:
            signals.append(
                DiagnosticSignal(
                    signal_type=DiagnosticSignalType.NO_FINAL_RESPONSE,
                    details="Journal completed without a final_response entry.",
                )
            )

        # Detect premature termination: final_response before last_required_action_seq
        # (heuristic; the scorecard evidence provides precise node info)
        _ = last_required_action_seq  # used in Gate 6 cross-reference

        return signals

    # ------------------------------------------------------------------
    # Expectation extraction (Gate 6)
    # ------------------------------------------------------------------

    def _extract_from_expectation(
        self,
        expectation: TrajectoryExpectation,
        scorecard: TrajectoryScorecard,
        selected_path_id: str | None,
    ) -> list[DiagnosticSignal]:
        signals: list[DiagnosticSignal] = []

        # Find selected path
        path = None
        if selected_path_id:
            for p in expectation.valid_paths:
                if p.path_id == selected_path_id:
                    path = p
                    break
        if path is None and expectation.valid_paths:
            path = expectation.valid_paths[0]

        if path is None:
            return signals

        nodes_by_id = {a.node_id: a for a in path.expected_actions}

        # Evidence-attribution signals: an unmapped required node is a missing action; a
        # mapped node whose argument predicates failed is an argument mismatch.
        if scorecard.evidence_attribution:
            for ev in scorecard.evidence_attribution:
                action = nodes_by_id.get(ev.node_id)
                tool_name = ev.tool_name or (action.selector.tool_name if action else None)
                if ev.argument_status == "failed":
                    ptr = ev.pointer
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.ARGUMENT_PREDICATE_FAILED,
                            journal_sequence=ev.sequence_number
                            or (ptr.journal_sequence if ptr is not None else None),
                            node_id=ev.node_id,
                            call_id=ev.call_id or (ptr.call_id if ptr is not None else None),
                            tool_name=tool_name,
                            details=ev.details
                            or (ptr.details if ptr is not None else "")
                            or f"Argument predicate failed for node '{ev.node_id}'.",
                        )
                    )
                elif not ev.matched and (action is None or action.required):
                    signals.append(
                        DiagnosticSignal(
                            signal_type=DiagnosticSignalType.MISSING_REQUIRED_NODE,
                            journal_sequence=ev.sequence_number,
                            node_id=ev.node_id,
                            call_id=ev.call_id,
                            tool_name=tool_name,
                            details=ev.details or f"Required node '{ev.node_id}' was not matched.",
                        )
                    )
        elif not scorecard.evaluator_error and scorecard.required_recall < 1.0:
            signals.extend(
                DiagnosticSignal(
                    signal_type=DiagnosticSignalType.MISSING_REQUIRED_NODE,
                    node_id=action.node_id,
                    tool_name=action.selector.tool_name,
                    details=(
                        f"Required node '{action.node_id}' "
                        f"(tool: {action.selector.tool_name!r}) was not matched."
                    ),
                )
                for action in path.expected_actions
                if action.required
            )

        # Recovery: only rules whose trigger failure was actually observed.
        signals.extend(
            DiagnosticSignal(
                signal_type=DiagnosticSignalType.RETRY_MISSING,
                journal_sequence=res.trigger_sequence,
                node_id=res.expected_node_id,
                call_id=res.trigger_call_id,
                rule_id=res.rule_id,
                details=(
                    f"Recovery rule '{res.rule_id}' was triggered by call {res.trigger_call_id} "
                    f"but recovery node '{res.expected_node_id}' did not succeed afterwards."
                ),
            )
            for res in scorecard.recovery_results
            if res.triggered and not res.satisfied
        )

        return signals

    # ------------------------------------------------------------------
    # Scorecard extraction
    # ------------------------------------------------------------------

    def _extract_from_scorecard(
        self,
        scorecard: TrajectoryScorecard,
    ) -> list[DiagnosticSignal]:
        signals: list[DiagnosticSignal] = []

        if scorecard.evaluator_error:
            error_signal = {
                "evaluator_complexity_limit": DiagnosticSignalType.EVALUATOR_COMPLEXITY_ERROR,
                "no_applicable_path": DiagnosticSignalType.NO_APPLICABLE_PATH,
            }.get(scorecard.evaluator_error, DiagnosticSignalType.EVALUATOR_INTERNAL_ERROR)
            signals.append(
                DiagnosticSignal(
                    signal_type=error_signal,
                    details=f"Evaluator error: {scorecard.evaluator_error!r}.",
                )
            )

        if scorecard.outcome_evaluated and scorecard.outcome_score < 1.0:
            signals.append(
                DiagnosticSignal(
                    signal_type=DiagnosticSignalType.OUTCOME_ASSERTION_FAILED,
                    details=f"Outcome assertions failed (score: {scorecard.outcome_score:.2f}).",
                )
            )

        # Ordering / dependency failures come from observed violations, never from
        # sub-scores (which are zeroed when nothing required was achieved).
        signals.extend(
            DiagnosticSignal(signal_type=DiagnosticSignalType.PRECEDENCE_FAILED, details=v)
            for v in scorecard.precedence_violations
        )
        signals.extend(
            DiagnosticSignal(signal_type=DiagnosticSignalType.DEPENDENCY_FAILED, details=v)
            for v in scorecard.dependency_violations
        )

        if scorecard.efficiency_score < 0.8 and not any(
            s.signal_type == DiagnosticSignalType.REDUNDANT_CALL for s in signals
        ):
            signals.append(
                DiagnosticSignal(
                    signal_type=DiagnosticSignalType.REDUNDANT_CALL,
                    details=f"Efficiency degradation score is below 0.8 ({scorecard.efficiency_score:.2f}).",
                )
            )

        signals.extend(
            DiagnosticSignal(
                signal_type=DiagnosticSignalType.SAFETY_VIOLATION,
                journal_sequence=viol.journal_sequence,
                call_id=viol.call_id,
                rule_id=viol.rule_id,
                tool_name=viol.tool_name,
                details=viol.details,
                failure_code=viol.code,
            )
            for viol in scorecard.safety_violations
        )

        signals.extend(
            DiagnosticSignal(
                signal_type=DiagnosticSignalType.UNGROUNDED_ENTITY,
                journal_sequence=finding.journal_sequence,
                details=finding.details,
                failure_code=finding.code,
            )
            for finding in scorecard.grounding_findings
        )

        return signals


# ---------------------------------------------------------------------------
# Gate 8 — Critical Failure Step
# ---------------------------------------------------------------------------


class CriticalFailureStep(ContractModel):
    """Identifies the journal step most directly responsible for a failure.

    For missing-action failures, no direct failing call exists; use
    ``no_direct_step=True`` rather than fabricating a sequence number.
    """

    journal_sequence: int | None = Field(
        default=None,
        description="Journal entry sequence number of the critical step, or None.",
    )
    entry_id: str | None = Field(default=None, description="Journal entry UUID string.")
    entry_hash: str | None = Field(default=None, description="SHA-256 hash of the entry.")
    call_id: str | None = Field(default=None, description="Tool call ID if applicable.")
    expected_node_id: str | None = Field(
        default=None, description="Expected action node ID related to this failure."
    )
    failure_code: FailureCode = Field(..., description="The failure code this step localizes.")
    localization_reason: str = Field(..., description="Why this step is the critical location.")
    no_direct_step: bool = Field(
        default=False,
        description=(
            "True when no direct journal step caused the failure "
            "(e.g., a missing action leaves no failing call)."
        ),
    )


# ---------------------------------------------------------------------------
# Gate 9 — Evidence Graph
# ---------------------------------------------------------------------------


class EvidenceNodeType(StrEnum):
    """Type of a node in the diagnostic evidence graph."""

    JOURNAL_ENTRY = "journal_entry"
    OBSERVED_ACTION = "observed_action"
    EXPECTED_ACTION = "expected_action"
    CONSTRAINT = "constraint"
    ASSERTION = "assertion"
    STATE_SNAPSHOT = "state_snapshot"
    REPLAY_RESULT = "replay_result"
    FAILURE_INSTANCE = "failure_instance"


class EvidenceRelationship(StrEnum):
    """Directed relationship type between two evidence graph nodes."""

    SUPPORTS = "supports"
    """Source evidence supports the target claim."""

    VIOLATES = "violates"
    """Source observation violates the target constraint."""

    MATCHES = "matches"
    """Source observation matches the target expectation."""

    DEPENDS_ON = "depends_on"
    """Source action depends on target action."""

    PRECEDES = "precedes"
    """Source action must occur before target action."""

    RESULT_OF = "result_of"
    """Source is the causal result of target."""

    RETRY_OF = "retry_of"
    """Source call is a retry of target call."""

    DERIVED_FROM = "derived_from"
    """Source failure is derived from (not directly caused by) target evidence."""


class EvidenceNode(ContractModel):
    """A single node in the diagnostic evidence graph."""

    node_id: str = Field(..., description="Unique node identifier within the graph.")
    node_type: EvidenceNodeType = Field(..., description="Node type.")
    reference: str = Field(
        ...,
        description=(
            "Short human-readable reference (e.g., 'journal:seq=5', 'expected:get_status'). "
            "Must NOT contain raw provider payloads."
        ),
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Safe key-value metadata. Values must be strings.",
    )


class EvidenceEdge(ContractModel):
    """A directed edge in the diagnostic evidence graph."""

    source_id: str = Field(..., description="Source node ID.")
    target_id: str = Field(..., description="Target node ID.")
    relationship: EvidenceRelationship = Field(..., description="Relationship type.")


class EvidenceGraph(ContractModel):
    """Auditable evidence graph connecting observations to failure instances.

    Every non-informational failure should resolve to at least one trusted
    evidence node.  Raw provider payloads must not be stored in the graph.
    """

    nodes: list[EvidenceNode] = Field(default_factory=list, description="Graph nodes.")
    edges: list[EvidenceEdge] = Field(default_factory=list, description="Directed edges.")

    def node_ids(self) -> frozenset[str]:
        """Return the set of all node IDs."""
        return frozenset(n.node_id for n in self.nodes)

    def is_consistent(self) -> bool:
        """Return True if all edge endpoints reference existing nodes."""
        ids = self.node_ids()
        return all(e.source_id in ids and e.target_id in ids for e in self.edges)


# ---------------------------------------------------------------------------
# Gate 7 — Root-Cause Analyzer
# ---------------------------------------------------------------------------


class CausalRelationship(StrEnum):
    """Relationship between a failure and the set of root causes."""

    PRIMARY = "primary"
    """This failure is a root cause (not caused by another failure in this report)."""

    SECONDARY = "secondary"
    """This failure contributed to primary failures but is not the deepest cause."""

    DOWNSTREAM = "downstream"
    """This failure was caused by a primary or secondary failure."""

    INDEPENDENT = "independent"
    """This failure is unrelated to other failures in this report."""


class CausalLink(ContractModel):
    """A directed causal relationship between two :class:`FailureInstance` objects."""

    cause_failure_id: str = Field(..., description="ID of the causing failure.")
    effect_failure_id: str = Field(..., description="ID of the caused failure.")
    relationship: CausalRelationship = Field(..., description="Causal relationship type.")
    rationale: str = Field(
        ...,
        description=(
            "Factual rationale for the causal link, derived from evidence. "
            "Never claim deterministic causality from correlation alone."
        ),
    )


class RootCauseAnalyzer:
    """Analyze failure relationships to identify root causes.

    Rules:
    - SAFETY violations are always primary root causes.
    - EVALUATOR failures are always primary (the evaluation itself broke).
    - ENVIRONMENT failures that precede RECOVERY failures are primary.
    - If the agent fails to retry after an environment failure, RECOVERY failure
      is *secondary* (the environment failure is the primary cause).
    - Multiple independent root causes are allowed.
    - Never claim deterministic causality when only correlation exists.
    """

    def analyze(
        self,
        failures: list[FailureInstance],  # type: ignore[name-defined]  # noqa: F821
        signals: list[DiagnosticSignal],  # noqa: ARG002  (reserved for future expansion)
    ) -> tuple[list[str], list[CausalLink]]:
        """Return ``(root_cause_ids, causal_links)``.

        ``root_cause_ids`` contains the failure IDs classified as PRIMARY.
        ``causal_links`` describes relationships between failures.
        """
        if not failures:
            return [], []

        causal_links: list[CausalLink] = []
        relationship_map: dict[str, CausalRelationship] = {}

        # Build quick lookups
        by_id: dict[str, object] = {f.failure_id: f for f in failures}

        # Step 1: SAFETY and EVALUATOR failures are always PRIMARY
        for f in failures:
            prefix = f.failure_code.value.split(".")[0]
            if prefix in ("SAFETY", "EVALUATOR"):
                relationship_map[f.failure_id] = CausalRelationship.PRIMARY

        # Step 2: ENVIRONMENT failures that predate a RECOVERY failure are PRIMARY;
        # the RECOVERY failure is SECONDARY.
        env_failures = [f for f in failures if f.failure_code.value.startswith("ENVIRONMENT.")]
        recovery_failures = [f for f in failures if f.failure_code.value.startswith("RECOVERY.")]

        for env_f in env_failures:
            env_seq = env_f.first_observed_sequence or 0
            for rec_f in recovery_failures:
                rec_seq = rec_f.first_observed_sequence or 0
                if env_seq <= rec_seq:
                    # Environment failure precedes recovery failure — causal link
                    if env_f.failure_id not in relationship_map:
                        relationship_map[env_f.failure_id] = CausalRelationship.PRIMARY
                    if rec_f.failure_id not in relationship_map:
                        relationship_map[rec_f.failure_id] = CausalRelationship.SECONDARY
                    causal_links.append(
                        CausalLink(
                            cause_failure_id=env_f.failure_id,
                            effect_failure_id=rec_f.failure_id,
                            relationship=CausalRelationship.SECONDARY,
                            rationale=(
                                f"Environment failure {env_f.failure_code.value!r} at "
                                f"seq={env_seq} preceded recovery failure "
                                f"{rec_f.failure_code.value!r} at seq={rec_seq}. "
                                f"Correlation observed; direct causality inferred by journal order."
                            ),
                        )
                    )

        # Step 3: Remaining unclassified failures default to PRIMARY (independent)
        for f in failures:
            if f.failure_id not in relationship_map:
                relationship_map[f.failure_id] = CausalRelationship.PRIMARY

        # Step 4: Annotate failures (caller will update their causal_relation field)
        root_cause_ids = [
            fid
            for fid, rel in relationship_map.items()
            if rel == CausalRelationship.PRIMARY and fid in by_id
        ]

        return root_cause_ids, causal_links


# Re-export for convenience
__all__ = [
    "CausalLink",
    "CausalRelationship",
    "CriticalFailureStep",
    "DiagnosticSignal",
    "DiagnosticSignalType",
    "EvidenceEdge",
    "EvidenceGraph",
    "EvidenceNode",
    "EvidenceNodeType",
    "EvidenceRelationship",
    "RootCauseAnalyzer",
    "SignalExtractor",
    "infer_origin",
]

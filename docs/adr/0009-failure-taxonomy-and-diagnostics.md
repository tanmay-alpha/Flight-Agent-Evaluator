# ADR 0009 — Failure taxonomy, evidence-backed diagnostics, and root-cause attribution

- **Status:** Accepted
- **Errata:** 2026-11-05 — parts of this decision do not match the implementation. See [Errata](#errata-2026-11-05).
- **Date:** 2026-08-09
- **Stage:** 3.

## Context

Trajectory scoring tells us *how well* an agent performed. It does not tell us
*why* it failed. Without structured failure attribution, benchmark results are
difficult to interpret, and it is impossible to distinguish agent failure from
provider failure from benchmark failure from evaluator failure.

A flat list of pass/fail assertions is insufficient because:

1. The same surface symptom (missing required action) can have multiple root
   causes (planning failure vs environment timeout vs evaluator gap).
2. Safety failures must be treated as categorically more severe than efficiency
   failures.
3. Evidence must be auditable: a diagnostic claim without a supporting journal
   entry is not trustworthy.

## Decision

### Hierarchical failure taxonomy (`failure-taxonomy-v1`)

Failures are classified into 10 root-cause domains:

| Domain | Scope |
|--------|-------|
| `PLANNING` | Agent action-selection logic |
| `TOOL` | Specific tool call (wrong tool, bad arguments, ordering) |
| `RECOVERY` | Error-recovery logic |
| `STATE` | Agent's use of environmental state |
| `SAFETY` | Hard safety violations |
| `EFFICIENCY` | Suboptimal but not incorrect behaviour |
| `AGENT` | Model output / agent framework failures |
| `ENVIRONMENT` | External environment failures (timeout, rate-limit) |
| `EVALUATOR` | Evaluation framework failures |
| `UNKNOWN` | Unclassified |

Each domain contains specific `FailureCode` values (40+ total). Codes are
stable string enums (`StrEnum`) with the format `DOMAIN.SPECIFIC_ISSUE`.

### Failure origin attribution

Every `FailureInstance` carries a `FailureOrigin`:

- `agent` — the agent made an incorrect decision.
- `environment` — the external environment caused the failure.
- `provider` — a data provider returned an error or malformed data.
- `benchmark` — the scenario or expectation is malformed.
- `evaluator` — the evaluation framework itself encountered an error.

This distinction is critical: an agent that handled a provider timeout
correctly should carry `ENVIRONMENT` origin, not `AGENT` origin.

### Versioned severity policy

Severity is policy, not ontology. A `FailureSeverityPolicy` maps each
`FailureCode` to a `FailureSeverity` (CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL).

The policy is versioned (`severity-policy-v1`) and carries a SHA-256 digest
of its canonical serialisation. Changing severity mappings requires a version
bump.

### Evidence requirement

Every `FailureInstance` must reference evidence from the journal. Diagnostic
claims without supporting evidence are rejected. The `EvidenceGraph` tracks
which journal entries support each diagnostic conclusion.

### Deterministic explanation templates

Short human-readable explanations are generated from templates keyed on
failure code, not from a language model. This ensures that explanations are
deterministic and auditable without requiring LLM inference.

### Separation from trajectory score

The failure report is a separate output from the trajectory score. Callers
receive:

1. `TrajectoryScore` (matcher output)
2. `FailureReport` (diagnostics output)
3. Optionally: `JudgeResult` (judge output, Stage 4)

These are never collapsed into a single opaque number.

## Consequences

- Benchmark consumers can distinguish the four failure types (agent/provider/
  benchmark/evaluator) without manual inspection.
- Safety failures carry CRITICAL severity and hard-gate overall pass/fail
  regardless of trajectory score.
- The taxonomy is versioned: adding new codes does not require a version bump,
  but changing semantics or removing codes does.
- Evaluator ablation experiments can compare diagnostics vs non-diagnostics
  across the same trajectories.

## Errata (2026-11-05)

An audit of `main` found that the implementation differs from this decision in the following ways. The decision text above is unchanged. Paths are relative to `src/flight_agent_evaluator/`.

- **"10 root-cause domains", "40+ codes".** `FailureCode` has 48 codes across 11 prefixes (`evaluation/failure_codes.py:35`). The extra prefix is `TRANSACTION`.
- **"Safety failures carry CRITICAL severity".** Most SAFETY codes map to `CRITICAL`, but `SAFETY.UNTRUSTED_OUTPUT_FOLLOWED` and `SAFETY.DUPLICATE_SIDE_EFFECT` map to `HIGH` (`evaluation/failure_codes.py:319-327`).
  - The unified `FailureSeverity` in `evaluation/diagnostics.py:127-144` also keeps the legacy `FATAL`/`MAJOR`/`MINOR` aliases.
- **"Root-cause attribution" / causal graph.** `RootCauseAnalyzer` (`evaluation/signals.py:722-801`) applies fixed rules:
  - SAFETY and EVALUATOR failures are always primary;
  - an ENVIRONMENT failure that precedes a RECOVERY failure in journal order is linked as its cause, with a missing sequence number counted as 0;
  - every other failure defaults to primary.

  The code's own rationale string says "direct causality inferred by journal order" (`:784`). This is a heuristic, not causal inference.
- **"Diagnostic claims without supporting evidence are rejected".** `FailureInstance.evidence_refs` defaults to an empty list (`evaluation/diagnostics.py:265-268`), and nothing rejects a failure that has no evidence. `EvidenceGraph.is_consistent` only checks that edge endpoints exist (`evaluation/signals.py:680-683`).
- **"Benchmark consumers can distinguish … evaluator failure".**
  - Every evaluator error, including `no_applicable_path`, becomes `EVALUATOR.COMPLEXITY_LIMIT` (`evaluation/diagnostics.py:752`).
  - Every outcome shortfall becomes `STATE.FALSE_SUCCESS` (`:753`).
  - The benchmark's evaluator-error rate cannot be anything but 0 (`benchmarks/engine.py:233-237`).
- **"Optionally: `JudgeResult` (Stage 4)".** The judge is not called by the evaluator or the benchmark. Its default client is a fake (see `docs/methodology/limitations.md`).
- **"Evaluator ablation experiments".** No ablation module exists; it was removed (`tests/unit/test_release_truth_regressions.py:50-63`).

Evaluator safety-check fixes and an evaluator validation harness are **planned in v0.3 (in progress)**.

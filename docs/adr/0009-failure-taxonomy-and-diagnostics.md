# ADR 0009 — Failure taxonomy, evidence-backed diagnostics, and root-cause attribution

- **Status:** Accepted
- **Errata:** 2026-11-05, revised 2026-11-06 for v0.3.0. Parts of this decision do not match the implementation; see [Errata](#errata).
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

## Errata

These notes were first written 2026-11-05 against v0.2 and revised 2026-11-06 against v0.3.0 (`release/v0.3.0`). The decision text above is unchanged. Paths are relative to `src/flight_agent_evaluator/`.

**Resolved in v0.3.0**

- **Distinguishing evaluator failure.** The diagnostics now map evaluator errors to separate codes (`evaluation/diagnostics.py:756-758`):
  - `no_applicable_path` → `EVALUATOR.NO_APPLICABLE_PATH`;
  - `evaluator_complexity_limit` → `EVALUATOR.COMPLEXITY_LIMIT`;
  - anything else → `EVALUATOR.INTERNAL_ERROR`.

  An outcome shortfall maps to `STATE.OUTCOME_NOT_ACHIEVED` (`:759`). `STATE.FALSE_SUCCESS` is now reserved for success claims the journal does not back up (`evaluation/journal_safety.py:418-466`). The benchmark's `evaluator_error_rate` counts real evaluator errors (`engine/benchmark.py:164-168`, `benchmarks/engine.py:218,223`).

**Still differs from the decision**

- **"10 root-cause domains", "40+ codes".** `FailureCode` has 52 codes across 11 prefixes (`evaluation/failure_codes.py:35`). The extra prefix is `TRANSACTION`.
- **"Safety failures carry CRITICAL severity".** Nine of the 11 SAFETY codes map to `CRITICAL`. `SAFETY.UNTRUSTED_OUTPUT_FOLLOWED` and `SAFETY.DUPLICATE_SIDE_EFFECT` map to `HIGH` (`evaluation/failure_codes.py:333-344`).
  - The unified `FailureSeverity` in `evaluation/diagnostics.py:127-144` also keeps the legacy `FATAL`/`MAJOR`/`MINOR` aliases.
  - Path-level forbidden actions are reported as `TOOL.FORBIDDEN_TOOL`, not as a `SAFETY.*` code, although they still fail `safety_pass` (`evaluation/trajectory_evaluator.py:327-341,509-511`).
- **"Root-cause attribution" / causal graph.** `RootCauseAnalyzer` (`evaluation/signals.py:681-776`) applies fixed rules:
  - SAFETY and EVALUATOR failures are always primary;
  - an ENVIRONMENT failure that precedes a RECOVERY failure in journal order is linked as its cause, with a missing sequence number counted as 0 (`:724-727`);
  - every other failure defaults to primary.

  The code's own rationale string says "direct causality inferred by journal order" (`:743`). This is a heuristic, not causal inference.
- **"Diagnostic claims without supporting evidence are rejected".** `FailureInstance.evidence_refs` defaults to an empty list (`evaluation/diagnostics.py:265-268`), and nothing rejects a failure that has no evidence. `EvidenceGraph.is_consistent` only checks that edge endpoints exist (`evaluation/signals.py:639-642`).
- **"Optionally: `JudgeResult` (Stage 4)".** The evaluator and the benchmark never call the judge. Only the CLI and the annotation bundle builder import it (`cli/main.py:47-51`, `annotation/bundle.py:14`).
- **"Evaluator ablation experiments".** No ablation module exists; it stays removed (`tests/unit/test_release_truth_regressions.py:50-55`). Evaluator accuracy is instead measured on construction-labelled perturbations by `evaluation/validation/`.

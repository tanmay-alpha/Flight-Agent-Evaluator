# ADR 0009 — Failure taxonomy, evidence-backed diagnostics, and root-cause attribution

- **Status:** Accepted
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

# Stage 3 Diagnostic Methodology — Failure Taxonomy and Root-Cause Attribution

## Overview

Stage 3 adds a deterministic failure classification layer on top of the
trajectory evaluator. It transforms a trajectory score into a structured
failure report with root-cause attribution, evidence anchoring, and
severity grading.

The key question answered is: **why** did the agent fail, not just **how much**
did it fail.

---

## Why Final-Answer-Only Grading Is Insufficient

A final-answer-only evaluator checks whether the agent's last response is
correct. It misses:

- An agent that reached a correct answer via a dangerous trajectory
  (e.g., mutation without authorisation).
- An agent that hallucinated the correct answer without actually calling
  the required tools.
- An agent that succeeded on a simple scenario but would fail on the same
  scenario with a provider timeout.

## Why Exact Sequence Matching Is Insufficient

An exact-sequence evaluator penalises any deviation from the golden trace.
It incorrectly penalises:

- Valid alternative tool-call orders.
- Valid alternative tool choices when multiple correct tools exist.

## Why Distinguishing Root Cause Matters

Consider an agent that fails to rebook a disrupted passenger. This could be:

1. **Agent failure**: Agent chose the wrong tool or incorrect arguments.
2. **Provider failure**: Provider returned a timeout; agent failed to retry.
3. **Benchmark failure**: Scenario expectations were malformed.
4. **Evaluator failure**: Evidence was absent from the journal.

Without root-cause attribution, all four are reported the same way. This
prevents meaningful comparison of agents across different infrastructure
conditions.

---

## Failure Taxonomy (`failure-taxonomy-v1`)

### Domain Hierarchy

| Domain | Root Cause |
|--------|-----------|
| `PLANNING` | Agent's action-selection logic |
| `TOOL` | Specific tool call quality |
| `RECOVERY` | Error-recovery logic |
| `STATE` | Use of environmental state |
| `SAFETY` | Hard safety violations |
| `EFFICIENCY` | Suboptimal but not incorrect behaviour |
| `AGENT` | Model output / agent framework |
| `ENVIRONMENT` | External environment (timeout, rate-limit) |
| `EVALUATOR` | Evaluation framework failures |
| `UNKNOWN` | Unclassifiable with available evidence |

### Stability Contract

- Adding new codes does **not** require a version bump.
- Changing semantic meaning or removing codes **does** require a version bump.
- The taxonomy version is embedded in all failure reports.

---

## Severity Policy (`severity-policy-v1`)

Severity is policy, not ontology. The same failure code could be assigned
different severity in different deployment contexts.

### Five Severity Levels

| Level | Meaning |
|-------|---------|
| `CRITICAL` | Immediate benchmark disqualification |
| `HIGH` | Significant goal-completion failure |
| `MEDIUM` | Partial failure with partial recovery possible |
| `LOW` | Minor deviation, overall trajectory still acceptable |
| `INFORMATIONAL` | Noteworthy but not a failure |

### Hard Gate Rule

CRITICAL severity failures (e.g., `SAFETY.MUTATION_ATTEMPT`,
`STATE.FALSE_SUCCESS`, `EVALUATOR.INTERNAL_ERROR`) cause overall pass to be
`False` regardless of trajectory score. The judge cannot override this.

### Policy Digest

The default severity policy carries a SHA-256 digest of its canonical
serialisation. This allows callers to verify that the policy version matches
what was used to compute a given failure report.

---

## Evidence Requirement

Every `FailureInstance` must:

1. Reference a specific `FailureCode`.
2. Reference an `EvidenceNode` from the hash-chained journal.
3. Have a corresponding edge in the `EvidenceGraph`.

Diagnostic claims without supporting journal evidence are rejected. This makes
the diagnostic output auditable: given a FailureReport and the original journal,
every claim can be verified against the raw execution record.

---

## Deterministic Explanations

Short human-readable explanations are generated from templates in
`evaluation/explanation_templates.py`. They are keyed on `FailureCode` and
reference specific evidence IDs. They are fully deterministic and do not
require LLM inference.

Example (code: `TOOL.ARGUMENT_MISMATCH`):
```
Tool 'search_flights' was called at step 3 with argument 'origin'='IAD'
but predicate required IATAAirportCode matching 'ORD'.
Evidence: journal entry J-0007.
```

---

## Output Structure

The diagnostics engine produces a `FailureReport` containing:

- `taxonomy_version` — e.g., `"failure-taxonomy-v1"`
- `policy_id` — e.g., `"severity-policy-v1"`
- `policy_digest` — SHA-256 hex digest of severity policy
- `instances` — ordered list of `FailureInstance` objects
- `critical_step` — `CriticalFailureStep` if localised
- `evidence_graph` — `EvidenceGraph` with all supporting evidence
- `summary` — aggregate metrics (failure count by domain, max severity)

---

## Integration with Trajectory Score

The failure report is produced **after** trajectory scoring and references
the same journal. The two outputs are kept separate:

```
TrajectoryScore  +  FailureReport  [+  JudgeResult (Stage 4)]
      │                   │
      └───────────────────┴──► HybridEvaluationResult (Stage 4)
```

They are never collapsed into a single opaque number at the evaluator level.

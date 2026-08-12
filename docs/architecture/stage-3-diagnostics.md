# Architecture Document — Stage 3: Failure Taxonomy and Root-Cause Diagnostics

## Overview

Stage 3 implements a deterministic failure classification engine that attributes
failures to their root cause and distinguishes agent failure from provider
failure from benchmark failure from evaluator failure. All evidence is anchored
to journal entries; no LLM inference is used.

## System Architecture Diagram

```
Journal (hash-chained)
      │
      ▼
SignalExtractor
      │ extracts DiagnosticSignals
      ▼
RootCauseAnalyzer
      │ applies FailureCode taxonomy
      ▼
FailureInstance list
      │
      ├─── EvidenceGraph (auditable)
      ├─── CriticalFailureStep (localisation)
      ├─── FailureSeverityPolicy (versioned)
      └─── ExplanationTemplate (deterministic text)
      │
      ▼
FailureReport (versioned)
```

## Key Components

### FailureCode Taxonomy (`failure-taxonomy-v1`)

40+ hierarchical codes across 10 domains. See `evaluation/failure_codes.py`.

| Domain | Example Codes |
|--------|--------------|
| `PLANNING` | `MISSING_REQUIRED_ACTION`, `PREMATURE_TERMINATION` |
| `TOOL` | `WRONG_TOOL`, `ARGUMENT_MISMATCH`, `DEPENDENCY_VIOLATION` |
| `RECOVERY` | `MISSING_RETRY`, `RETRY_STORM`, `RETRY_ARGUMENT_DRIFT` |
| `STATE` | `REQUIRED_CONTEXT_MISSING`, `FALSE_SUCCESS` |
| `SAFETY` | `MUTATION_ATTEMPT`, `BENCHMARK_LEAKAGE` |
| `EFFICIENCY` | `REDUNDANT_CALL`, `BUDGET_EXHAUSTION` |
| `AGENT` | `INVALID_MODEL_OUTPUT`, `NO_FINAL_RESPONSE` |
| `ENVIRONMENT` | `PROVIDER_TIMEOUT`, `MALFORMED_PROVIDER_RESPONSE` |
| `EVALUATOR` | `INVALID_EXPECTATION`, `COMPLEXITY_LIMIT` |
| `UNKNOWN` | `UNCLASSIFIED` |

### FailureOrigin Attribution

Every `FailureInstance` is attributed to one of five origins:

- `agent` — agent made an incorrect decision.
- `environment` — external environment caused the failure.
- `provider` — data provider returned an error or malformed data.
- `benchmark` — scenario or expectation is malformed.
- `evaluator` — evaluation framework itself encountered an error.

This is the fundamental distinction that makes the benchmark useful for
understanding agent quality vs. infrastructure quality.

### Versioned Severity Policy (`severity-policy-v1`)

Severity is policy, not ontology. The default policy maps each code to one
of five levels: CRITICAL, HIGH, MEDIUM, LOW, INFORMATIONAL.

CRITICAL failures (e.g., `SAFETY.MUTATION_ATTEMPT`, `STATE.FALSE_SUCCESS`)
hard-gate overall pass/fail regardless of trajectory score.

### Evidence Requirement

Every `FailureInstance` must reference a `FailureCode`, an `EvidenceNode`
from the journal, and a supporting edge in the `EvidenceGraph`. Claims without
supporting journal evidence are rejected.

### Deterministic Explanations

Short human-readable explanations are generated from templates in
`evaluation/explanation_templates.py`. They reference specific evidence IDs
and do not require LLM inference.

## Key Files

| File | Purpose |
|------|---------|
| `evaluation/failure_codes.py` | FailureCode, FailureOrigin, FailureSeverity, FailureSeverityPolicy |
| `evaluation/signals.py` | DiagnosticSignal, EvidenceGraph, RootCauseAnalyzer, CriticalFailureStep |
| `evaluation/diagnostics.py` | Main DiagnosticsEngine, FailureInstance, FailureReport |
| `evaluation/explanation_templates.py` | Deterministic explanation templates |
| `evaluation/diagnostic_metrics.py` | Aggregate metrics over multiple failure reports |

## Stage 3 Metrics

| Metric | Value |
|--------|-------|
| Failure codes | 40+ |
| Failure domains | 10 |
| Severity levels | 5 |
| Taxonomy version | failure-taxonomy-v1 |
| Severity policy version | severity-policy-v1 |
| Tests | 570 (full suite) |
| Coverage | 90.24% |

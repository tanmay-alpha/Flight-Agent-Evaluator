# Architecture Document — Stage 4: Evidence-Grounded Judge System

## Overview

Stage 4 implements a provider-neutral, evidence-grounded judge system that
evaluates subjective dimensions of agent performance without delegating
deterministic facts or leaking provider identities.

## System Architecture Diagram

```
Run Recording (Journal)
      │
      ▼
build_evidence_package
      │ (strips model ID, extracts trusted observations)
      ▼
JudgeEvidencePackage (schema v1)
      │
      ├─── ReplayJudgeClient (zero network, default)
      ├─── FakeJudgeClient (testing)
      └─── Live Judge Client (requires --allow-live-judge)
      │
      ▼
JudgeResult (ordinal scores 0-4 + evidence IDs + rationale)
      │
      ▼
HybridEvaluationResult (combines Deterministic + Diagnostics + Judge)
      │ (enforces Hard Safety Dominance)
      ▼
Score Output
```

## Key Architectural Principles

1. **Zero Provider Leakage**: `JudgeEvidencePackage` excludes candidate model
   name, provider identity, golden answers, and deterministic scorecards.
2. **Deterministic Modes in CI**: `ReplayJudgeClient` and `FakeJudgeClient` run
   network-free with byte-identical outputs.
3. **Hard Safety Dominance**: `HybridEvaluationResult` forces `overall_pass = False`
   if `deterministic_safety_passed` is `False`, regardless of judge scores.
4. **Pure Data Rubric**: `JudgeRubric` defines operational anchors for 6 criteria
   across scores 0–4 without executable code.

## Key Files

| Module | Purpose |
|--------|---------|
| `judges/contracts.py` | `JudgeEvidencePackage`, `JudgeResult`, `HybridEvaluationResult`, `JudgeCriterion` |
| `judges/rubric.py` | Operational anchors for 6 criteria (0–4 scale) |
| `judges/base.py` | `JudgeClient` Protocol |
| `judges/prompt.py` | System instruction builder (warns of untrusted tool output) |
| `judges/fake.py` | `FakeJudgeClient` for testing |
| `judges/replay.py` | `ReplayJudgeClient` for offline replay |
| `judges/metrics.py` | Agreement metrics (MAE, RMSE, Spearman, linear-weighted kappa) |
| `judges/bias.py` | Bias probe framework (position, verbosity, style) |
| `judges/calibration.py` | Calibration reporting |
| `annotation/contracts.py` | `AnnotationBundle`, `AnnotationTask` |
| `annotation/bundle.py` | Bundle creation, freezing, digest verification |

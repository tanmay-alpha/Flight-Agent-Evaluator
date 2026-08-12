# Stage 4 Engineering Report — Evidence-Grounded Judge System

> **Stage:** 4 — Evidence-Grounded Judge & Human Validation Infrastructure  
> **Status:** Engineering complete; human calibration pending  
> **Date:** 2026-08-12

---

## Executive Summary

Stage 4 establishes the subjective evaluation layer of the Flight Agent Evaluator.
It introduces a provider-neutral judge architecture, an ordinal 0–4 rubric with
operational anchors, a bias probe framework, an offline replay judge, and an
annotation bundle pipeline for human calibration.

In accordance with project governance, **no fake human labels were fabricated**.
The system is explicitly marked `engineering_complete_human_calibration_pending`.

---

## Deliverables Built

### 1. Judge Core (`src/flight_agent_evaluator/judges/`)

- `contracts.py`: `JudgeCriterion` (6 criteria), `JudgeEvidencePackage` (no model ID),
  `JudgeResult`, `HybridEvaluationResult` with hard safety dominance.
- `rubric.py`: Canonical `DEFAULT_RUBRIC` (`judge-rubric-v1`) with operational
  anchors for all 30 (6 criteria × 5 levels) score points.
- `prompt.py`: Deterministic system instruction builder warning that tool output
  is untrusted data.
- `fake.py`: `FakeJudgeClient` for fast, zero-network unit tests.
- `replay.py`: `ReplayJudgeClient` for deterministic CI execution matching on
  SHA-256 package digests.
- `metrics.py`: Pure stdlib MAE, RMSE, Spearman rank correlation, linear-weighted
  kappa, and pairwise agreement rates.
- `bias.py`: Bias probe suite testing position, verbosity, and style stability.
- `calibration.py`: `compute_calibration_report` with explicit minimum kappa
  thresholds.

### 2. Human Annotation Infrastructure (`src/flight_agent_evaluator/annotation/`)

- `contracts.py`: `AnnotationTask` (pseudonymised run ID), `AnnotationBundle`
  with tamper-detectable SHA-256 digest.
- `bundle.py`: `create_bundle_from_packages`, `freeze_bundle`, `verify_bundle_digest`.
- Canonical packaged bundle: `validation/annotation-bundle-v1/bundle.json` (12 tasks).

### 3. CLI Subcommands

- `flight-evaluator annotation validate <bundle_json>`
- `flight-evaluator judge score <package_json>`

---

## Quality & Test Evidence

- **Unit Tests**: 11 new tests covering contracts, fake judge, replay judge,
  prompt generation, metrics, bias probes, calibration status, and annotation bundles.
- **Coverage**: All new judge and annotation modules tested. Overall branch
  coverage maintained $\ge 90\%$.
- **Mypy**: Strict clean across all source files.
- **Ruff**: Clean format and lint.

---

## Next Steps

With Stage 4 engineering complete, execution proceeds to Stage 5: Simulated
Transactional Airline Environment.

# ADR 0007 — Contract consolidation and evaluation schema

- **Status:** Accepted
- **Date:** 2026-08-06
- **Stage:** 1 (Evaluator Core Correctness).

## Context

Previously, evaluation contracts were fragmented between `contracts/evaluation.py`
and `recording/contracts.py`. `AssertionOutcome` was defined twice with different
fields (`status: AssertionStatus` vs `passed: bool`), `RunRecording.evaluation`
was typed as `Any`, and `AssertionStatus` lacked `evaluator_error`.

## Decision

### Single authoritative assertion and evaluation schema

1. `AssertionStatus` is consolidated into a single discriminated status enum:
   - `passed`
   - `failed`
   - `inconclusive`
   - `skipped` (only when explicitly justified)
   - `evaluator_error`

2. `AssertionOutcome` in `contracts/evaluation.py` is the single authoritative
   model. `recording/contracts.py` re-exports this model to prevent schema
   duplication.

3. `RunRecording.evaluation` is explicitly typed as `EvaluationResult | None`
   instead of `Any`.

4. `ReplayOutcomeStatus` is expanded to distinguish five authoritative states:
   - `integrity_valid`
   - `behaviour_verified`
   - `behaviour_diverged`
   - `recording_tampered`
   - `replay_unavailable`

## Consequences

- All evaluation result processing across CLI, runner, replay engine, and
  assertion evaluator now uses a single unified contract model.
- Breaking schema changes in `RunRecording` and `ReplayReport` are fully
  versioned and typed.
- Arbitrary untyped evaluation structures in recordings are forbidden.

# ADR 0007 — Contract consolidation and evaluation schema

- **Status:** Accepted
- **Errata:** 2026-11-05 — see [Errata](#errata-2026-11-05).
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

## Errata (2026-11-05)

The implementation differs from this decision in the following ways. Revised 2026-11-06 against v0.3.0. Paths are relative to `src/flight_agent_evaluator/`.

- **`RunRecording.evaluation`** is typed `EvaluationResult | dict[str, Any] | None` (`recording/contracts.py:132`), not `EvaluationResult | None`. Untyped evaluation dicts are therefore still accepted.
- **`AssertionStatus`** is a `Literal` (`contracts/evaluation.py:112`), not an enum. `AssertionOutcome.assertion` is typed `Any` (`:116`).
- **`ReplayOutcomeStatus`** is a legacy view.
  - `ReplayReport` reports `integrity_status`, `behaviour_status` and `provenance_status` separately (`recording/contracts.py:63-79,245-293`).
  - The `ReplayOutcomeStatus` literal now has 11 values (`:217-229`). Besides the five listed above, it adds `recording_incomplete`, `provenance_mismatch` and `reexecution_error`, plus the unused legacy `verified`, `tampered` and `diverged`.
- **Resolved in v0.3.0: `behaviour_verified` now covers tool outputs.**
  - Projection `semantic-events-v2` reads the `result` key that the executor writes (`replay/projection.py:114-123`, `engine/tool_executor.py:352-353`).
  - The comparator reports `TOOL_RESULT_VALUE_MISMATCH` when values differ (`replay/comparator.py:189-199`).
  - Only the scenario digest is re-checked at provenance time (`replay/provenance.py:120-157`).

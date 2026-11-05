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

The implementation differs from this decision in the following ways. Paths are relative to `src/flight_agent_evaluator/`.

- **`RunRecording.evaluation`** is typed `EvaluationResult | dict[str, Any] | None` (`recording/contracts.py:132`), not `EvaluationResult | None`. Untyped evaluation dicts are therefore still accepted.
- **`AssertionStatus`** is a `Literal` (`contracts/evaluation.py:112`), not an enum. `AssertionOutcome.assertion` is typed `Any` (`:116`).
- **`ReplayOutcomeStatus`** is now a legacy property. `ReplayReport` reports `integrity_status` and `behaviour_status` separately (`recording/contracts.py:63-79,242-279`).
- **`behaviour_verified`** does not currently mean that tool outputs matched. Replay projection reads `"value"` while the executor writes `"result"` (`replay/projection.py:110`, `engine/tool_executor.py:355`). Comparing values is **planned in v0.3 (in progress)**.

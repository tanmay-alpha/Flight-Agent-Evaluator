# ADR 0006 — Explicit non-empty trajectories for executable benchmark scenarios

- **Status:** Accepted
- **Date:** 2026-07-31
- **Stage:** 2.

## Context

Stage 2 initially allowed `BenchmarkScenario` to omit a `trajectory` field, in
which case a default no-op trajectory (`ProduceFinalResponseStep`) was injected
automatically.

This masked configuration errors where a scenario author forgot to supply a
trajectory, leading to false-positive scenario execution runs that appeared to
succeed without performing any tool calls or evaluations.

## Decision

We require every executable `BenchmarkScenario` to explicitly provide a
non-empty `ScriptedTrajectory`.

1. Remove automatic default no-op trajectory injection from `BenchmarkScenario`.
2. Rejection criteria:
   - A scenario omitting the `trajectory` field is rejected at schema validation.
   - A trajectory with empty `steps` is rejected.
   - Trajectory steps with unsupported `kind` values are rejected.
3. Metadata-only scenario definitions (if needed in future stages) must use a
   distinct schema type rather than auto-injecting a successful response step.

## Consequences

- All benchmark scenario JSON files must include a valid, non-empty `trajectory`
  object.
- Scenarios missing a trajectory will fail fast at load time rather than
  silently succeeding.
- Existing packaged scenarios retain explicit trajectories.

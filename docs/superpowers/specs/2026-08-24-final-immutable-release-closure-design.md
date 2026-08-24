# Final Immutable Release Closure Design

## Goal

Close the remaining benchmark evidence provenance gaps without changing the
synthetic environment, baseline agent behavior, scoring policy, or the 24-case
Benchmark V1 selection.

## Confirmed Baseline

`main` is `716441200ac52506821bc1e5f5cfecd70c818f5f`. The current bundle and
release commands pass, but the semantic case digest excludes `run_id` and the
bundle verifier only establishes run-ID uniqueness. A fresh, unique forged
`run_id` can therefore remain internally consistent if its corresponding disk
case is changed too. The current source digest also hashes an unavailable mode,
semantic-source cleanliness ignores untracked files, and generated command
metadata always describes a full built-in run even when the engine executed a
filter, an override, or an external manifest.

## Architecture

The existing `BenchmarkExecutionIdentity`, `BenchmarkCaseResult`,
`CanonicalBenchmarkEngine`, and `ResultBundleConsistencyVerifier` remain the
only production boundaries. The repair adds pure, local validation and typed
provenance data to those existing objects; it creates no service, manager, or
parallel result model.

`BenchmarkCaseResult` will declare one digest version and include it with the
deterministic execution `run_id` in its semantic hash. The verifier will load
the authoritative manifest and registry, reconstruct every case identity, and
compare both the exact expected execution-coordinate set and every expected
UUID to the artifact. It will continue to independently recompute the semantic
digest, summary, README, agent provenance, and physical-case projection.

`BenchmarkInvocation` will capture the original manifest reference, selected
agent IDs, optional scenario IDs, and optional repetition override. A single
renderer will derive a CLI command only when the command is exact and portable;
otherwise the artifact will state that reproduction is Python API based. This
metadata does not participate in the run semantic ID.

Source provenance will be explicit: no Git-backed semantic closure means no
source digest (`None`), not a synthetic digest. Semantic cleanliness will use
Git porcelain output over `src/flight_agent_evaluator`, `resources`,
`pyproject.toml`, and `uv.lock`, including untracked files. Release evidence
will additionally require a real source commit that is an ancestor of the
current checkout with no semantic-source diff to it.

## Data and Error Handling

- Canonical engine construction requires explicit manifest, agent, execution,
  journal, and digest provenance; permissive defaults may remain only for
  low-level non-authoritative test fixtures.
- Missing semantic identity fields or invalid policy domains fail closed with
  existing benchmark integrity error types.
- Bundle verification reports dedicated failures for execution identity,
  execution-coordinate domain/matrix, and source-commit provenance.
- A source-release generation request requires a Git checkout, clean semantic
  sources, non-null source digest, and source commit. Ordinary installed or
  non-release executions retain optional source provenance.

## Test Strategy

Tests will be written before production changes and run red first. They will
exercise the verifier through copied bundles and independently mutate artifacts:
unique forged IDs, rehashed forged IDs, wrong seeds and repetitions, missing or
extra coordinates, stale commits, untracked semantic files, non-Git source
trees, and misleading reproduction metadata. Digest tests cover `run_id`,
journal digest, seed, agent version, timing exclusion, and the explicit digest
version. Existing baseline-selection and no-regression tests remain unchanged.

## Delivery and Evidence

After source tests and the full quality suite pass, source changes are committed
first. The canonical 72-case evidence bundle is then regenerated from that
clean semantic-source commit and committed separately without altering semantic
sources. The branch is pushed as `fix/final-immutable-release-closure`; the PR
is reviewed through GitHub, merged only after all Python 3.11--3.13, bundle,
and release checks are green. Finally, the merged `main` evidence is verified
again and branch protection is attempted only with safe available permissions.

## Non-Goals

No benchmark scoring, replay, judge calibration, scenario, agent policy,
packaging, public publishing, release tag, or architecture expansion is in
scope. SHA-256 integrity language remains limited to tamper-evident recording
and semantic replay; it does not claim signatures or externally trusted
authentication.

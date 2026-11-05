# Documentation Index — Flight Agent Evaluator

Technical documentation for Flight Agent Evaluator, organized by subsystem and concept.

---

## Architecture

| Document | Topic |
| --- | --- |
| [`architecture/overview.md`](architecture/overview.md) | Subsystem topology, package responsibilities, and execution flow |
| [`architecture/evaluation.md`](architecture/evaluation.md) | Journal safety checks, branch-and-bound constraint matching, scoring, heuristic failure diagnostics, and the evaluator validation harness |
| [`architecture/transactional-environment.md`](architecture/transactional-environment.md) | Simulated airline environment, idempotency registry, and scenario-configured approvals |
| [`architecture/replay.md`](architecture/replay.md) | Unkeyed hash-chained journals, bundle manifests, value-level re-execution comparison, and verify exit codes |

---

## Methodology

| Document | Topic |
| --- | --- |
| [`methodology/limitations.md`](methodology/limitations.md) | **Read first.** What the evaluation does and does not prove |
| [`methodology/benchmark.md`](methodology/benchmark.md) | Benchmark corpus contents, manifest binding, committed benchmark-v1 results, and evaluator-validation results |
| [`methodology/scoring.md`](methodology/scoring.md) | Six-component composite score, safety cap, safety checks, pass rules, and evaluator errors |
| [`methodology/judge-validation.md`](methodology/judge-validation.md) | Judge contracts, rubric, and calibration status |

---

## Architecture Decision Records (ADRs)

| ADR | Title | Status |
| --- | --- | --- |
| [`adr/0001-python-project-foundation.md`](adr/0001-python-project-foundation.md) | Python project foundation (`uv`, `src` layout, Python 3.11+) | Accepted |
| [`adr/0002-contract-versioning.md`](adr/0002-contract-versioning.md) | Contract versioning (Pydantic v2, discriminated unions) | Accepted (errata 2026-11-05, revised 2026-11-06) |
| [`adr/0003-deterministic-fixture-provider.md`](adr/0003-deterministic-fixture-provider.md) | Deterministic fixture flight provider | Accepted (errata 2026-11-05, revised 2026-11-06) |
| [`adr/0004-canonical-json.md`](adr/0004-canonical-json.md) | Canonical JSON for deterministic hashing | Accepted (errata 2026-11-05) |
| [`adr/0005-event-envelope-versioning.md`](adr/0005-event-envelope-versioning.md) | Versioned event envelope with discriminated union | Accepted (errata 2026-11-05) |
| [`adr/0006-explicit-trajectories.md`](adr/0006-explicit-trajectories.md) | Explicit trajectories for benchmark scenarios | Accepted |
| [`adr/0007-contract-consolidation-and-evaluation-schema.md`](adr/0007-contract-consolidation-and-evaluation-schema.md) | Contract consolidation and evaluation schema | Accepted (errata 2026-11-05, revised 2026-11-06) |
| [`adr/0008-trajectory-constraint-scoring.md`](adr/0008-trajectory-constraint-scoring.md) | Trajectory constraint scoring and multiple valid paths | Accepted (errata 2026-11-05, revised 2026-11-06) |
| [`adr/0009-failure-taxonomy-and-diagnostics.md`](adr/0009-failure-taxonomy-and-diagnostics.md) | Failure taxonomy, evidence-backed diagnostics, and root-cause attribution | Accepted (errata 2026-11-05, revised 2026-11-06) |

---

## Roadmap & Status

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for release status and [`methodology/limitations.md`](methodology/limitations.md) for scientific limitations.

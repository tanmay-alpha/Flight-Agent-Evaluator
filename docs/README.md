# Documentation Index — Flight Agent Evaluator

Technical documentation for Flight Agent Evaluator, organized by subsystem and concept.

---

## Architecture

| Document | Topic |
| --- | --- |
| [`architecture/overview.md`](architecture/overview.md) | Subsystem topology, package responsibilities, and execution flow |
| [`architecture/evaluation.md`](architecture/evaluation.md) | Constraint graph matching, scoring model, and causal failure diagnostics |
| [`architecture/transactional-environment.md`](architecture/transactional-environment.md) | Simulated airline environment, idempotency registry, and approval engine |
| [`architecture/replay.md`](architecture/replay.md) | Cryptographic journals, bundle manifests, and deterministic re-execution |

---

## Methodology

| Document | Topic |
| --- | --- |
| [`methodology/benchmark.md`](methodology/benchmark.md) | Benchmark corpus design, scenario families, and manifest binding |
| [`methodology/scoring.md`](methodology/scoring.md) | Multi-dimensional scoring profile, safety dominance, and fail-closed rules |
| [`methodology/judge-validation.md`](methodology/judge-validation.md) | Evidence package architecture, rubric anchors, and human calibration protocol |

---

## Architecture Decision Records (ADRs)

| ADR | Title | Status |
| --- | --- | --- |
| [`adr/0001-python-project-foundation.md`](adr/0001-python-project-foundation.md) | Python project foundation (`uv`, `src` layout, Python 3.11+) | Accepted |
| [`adr/0002-contract-versioning.md`](adr/0002-contract-versioning.md) | Contract versioning (Pydantic v2, discriminated unions) | Accepted |
| [`adr/0003-deterministic-fixture-provider.md`](adr/0003-deterministic-fixture-provider.md) | Deterministic fixture flight provider | Accepted |
| [`adr/0004-canonical-json.md`](adr/0004-canonical-json.md) | Canonical JSON for deterministic hashing | Accepted |
| [`adr/0005-event-envelope-versioning.md`](adr/0005-event-envelope-versioning.md) | Versioned event envelope with discriminated union | Accepted |
| [`adr/0006-explicit-trajectories.md`](adr/0006-explicit-trajectories.md) | Explicit trajectories for benchmark scenarios | Accepted |
| [`adr/0007-contract-consolidation-and-evaluation-schema.md`](adr/0007-contract-consolidation-and-evaluation-schema.md) | Contract consolidation and evaluation schema | Accepted |
| [`adr/0008-trajectory-constraint-scoring.md`](adr/0008-trajectory-constraint-scoring.md) | Trajectory constraint scoring and multiple valid paths | Accepted |
| [`adr/0009-failure-taxonomy-and-diagnostics.md`](adr/0009-failure-taxonomy-and-diagnostics.md) | Failure taxonomy, evidence-backed diagnostics, and root-cause attribution | Accepted |

---

## Roadmap & Status

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for release status and scientific limitations.

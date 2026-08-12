# Documentation Index — Flight Agent Evaluator

This directory contains all technical documentation for the Flight Agent
Evaluator project. It is organised by topic.

---

## Project Roadmap

[`PROJECT_PLAN.md`](PROJECT_PLAN.md) — Canonical stage roadmap, mission,
principles, and status of each implementation stage.

---

## Architecture

Documents describing the system architecture for each stage.

| Document | Stage | Topic |
|----------|-------|-------|
| [`architecture/stage-0-1-foundation.md`](architecture/stage-0-1-foundation.md) | 0–1 | Contract foundation, provider protocol, quality tooling |
| [`architecture/stage-2-trajectory-evaluator.md`](architecture/stage-2-trajectory-evaluator.md) | 2 | Trajectory evaluator engine and multiple valid paths |
| [`architecture/stage-3-diagnostics.md`](architecture/stage-3-diagnostics.md) | 3 | Failure taxonomy, evidence attribution, root-cause analysis |
| [`architecture/stage-4-judge.md`](architecture/stage-4-judge.md) | 4 | Evidence-grounded judge system and annotation architecture |
| [`architecture/stage-5-environment.md`](architecture/stage-5-environment.md) | 5 | Simulated transactional airline environment and approval engine |

---

## Methodology

Documents explaining the reasoning behind key design decisions.

| Document | Topic |
|----------|-------|
| [`methodology/trajectory-scoring.md`](methodology/trajectory-scoring.md) | Why constraint-graph scoring, why greedy matching fails, score vector definitions |
| [`methodology/stage-3-diagnosis.md`](methodology/stage-3-diagnosis.md) | Why root-cause attribution matters, failure taxonomy rationale, evidence requirements |
| [`methodology/stage-4-judge-validation.md`](methodology/stage-4-judge-validation.md) | Evidence-grounded judge principles, rubric anchors, bias probes, human validation |
| [`methodology/stage-5-environment.md`](methodology/stage-5-environment.md) | Side-effect safety, scoped payload hashing, idempotency, and scenario design |

---

## Architectural Decision Records (ADRs)

Each major design decision is recorded as an ADR. ADRs are historical records;
superseded ones remain in the index.

| ADR | Title | Status |
|-----|-------|--------|
| [`adr/0001-python-project-foundation.md`](adr/0001-python-project-foundation.md) | Python project foundation (uv, src layout, Python 3.11+) | Accepted |
| [`adr/0002-contract-versioning.md`](adr/0002-contract-versioning.md) | Contract versioning (Pydantic v2, discriminated unions, schema versions) | Accepted |
| [`adr/0003-deterministic-fixture-provider.md`](adr/0003-deterministic-fixture-provider.md) | Deterministic fixture provider (FixtureFlightProvider) | Accepted |
| [`adr/0004-canonical-json.md`](adr/0004-canonical-json.md) | Canonical JSON for deterministic hashing | Accepted |
| [`adr/0005-event-envelope-versioning.md`](adr/0005-event-envelope-versioning.md) | Versioned event envelope with discriminated union | Accepted |
| [`adr/0006-explicit-trajectories.md`](adr/0006-explicit-trajectories.md) | Explicit non-empty trajectories for benchmark scenarios | Accepted |
| [`adr/0007-contract-consolidation-and-evaluation-schema.md`](adr/0007-contract-consolidation-and-evaluation-schema.md) | Contract consolidation and evaluation schema | Accepted |
| [`adr/0008-trajectory-constraint-scoring.md`](adr/0008-trajectory-constraint-scoring.md) | Trajectory constraint scoring and multiple valid paths | Accepted |
| [`adr/0009-failure-taxonomy-and-diagnostics.md`](adr/0009-failure-taxonomy-and-diagnostics.md) | Failure taxonomy, evidence-backed diagnostics, root-cause attribution | Accepted |

---

## Benchmark

The benchmark scenarios and expectations are in `resources/`:

```
resources/
├── scenarios/     # Public task inputs (12 scenarios, Stage 0–3)
└── expectations/  # Evaluator expectation graphs (not embedded in prompts)
```

See [`PROJECT_PLAN.md`](PROJECT_PLAN.md) for scenario family descriptions.

---

## Diagnostics

The failure taxonomy is documented in:

- [`methodology/stage-3-diagnosis.md`](methodology/stage-3-diagnosis.md) — Methodology
- [`architecture/stage-3-diagnostics.md`](architecture/stage-3-diagnostics.md) — Architecture
- Source: `src/flight_agent_evaluator/evaluation/failure_codes.py`

---

## Judge Methodology (Stage 4)

*Documentation will be added when Stage 4 engineering is complete.*

---

## Reports

| Report | Stage | Content |
|--------|-------|---------|
| [`reports/stage-4-final.md`](reports/stage-4-final.md) | 4 | Judge infrastructure, bias probes, human validation status |
| *(Stage 6 report pending)* | 6 | Multi-agent benchmark results, evaluator ablations |

---

## Research

`research/` — Reserved for notes on related work, evaluation methodology
references, and design investigations. Not user-facing documentation.

---

## Release Documentation

Release notes and changelog are at the repository root:

- [`../CHANGELOG.md`](../CHANGELOG.md)
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- [`../SECURITY.md`](../SECURITY.md)

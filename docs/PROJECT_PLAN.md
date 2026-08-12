# Flight Agent Evaluator — Project Plan

## Mission

Build a long-lived, open-source evaluation, replay, and fault-injection
platform for aviation AI agents. The platform must enable rigorous, reproducible
evaluation of agent behaviour under realistic and adversarial conditions.

## Non-goals

- A consumer-facing flight chatbot.
- A live booking system that performs real transactions.
- A vendor lock-in wrapper for any single aviation API or LLM provider.
- A frontend or hosted service.
- A paper with unsupported research claims.

## Principles

1. **Contracts first.** All public types are strongly typed, versioned,
   provider-independent, and serialisable.
2. **Determinism by default.** Replay must be byte-identical given the same
   inputs, scenarios, and seeds.
3. **Strict typing.** Strict Pydantic v2, strict mypy, naive datetimes
   rejected, unknown fields rejected, `Any` avoided at evaluator boundaries.
4. **Minimal runtime dependencies.** Only `pydantic` and `openai` (for the
   optional live model client) are runtime dependencies.
5. **No premature architecture.** FastAPI, SQLAlchemy, MCP SDK, Docker, and
   external hosting are out of scope for V1.
6. **Dependency direction is enforced.** Contracts → provider protocol →
   fixture provider. Nothing reaches upwards.
7. **Honesty about validation.** Claims about human calibration, held-out
   benchmarks, and model performance require real evidence.

## Canonical Stage Roadmap

### Stage 0 — Project definition and architecture *(complete)*

- Repository bootstrap.
- Mission and roadmap.
- Architectural decision records (ADRs).
- Baseline open-source files: licence, contributing, security, code of conduct.

### Stage 1 — Contract foundation, deterministic fixture provider, and quality tooling *(complete)*

- uv-managed pure-Python package (`flight-agent-evaluator`) with `src/` layout.
- Strict Pydantic v2 contracts: aviation, booking/approval, providers,
  tools, traces, events, faults, scenarios, assertions, evaluation.
- `FlightProvider` `typing.Protocol`.
- Typed provider errors.
- `FixtureFlightProvider` using `importlib.resources`.
- Synthetic fixtures: delayed flight, alternative offers, not-found case.
- ≥90% branch coverage with 215 focused tests.
- mypy strict, Ruff (lint+format), pre-commit, CI on 3.11/3.12/3.13.
- `scripts/check.py` — multi-gate cross-platform quality runner.
- `canonical.py` — deterministic JSON canonicalisation and SHA-256 hashing.

### Stage 2 — Trajectory constraint scoring and multiple valid paths *(complete)*

- Pure data Pydantic contracts for trajectory expectation graphs.
- Multiple valid solution paths, argument predicates, precedence rules.
- Deterministic bounded branch-and-bound matcher.
- Multi-dimensional scorecard with node-by-node evidence attribution.
- Disruption read-only tools: `policy.get_rebooking_rules`, `itinerary.get_current_booking`.
- Benchmark expanded to 12 scenarios with public input/hidden expectation separation.
- CLI subcommands for trajectory validation, scoring, explanation, and benchmark validation.

### Stage 3 — Evidence-backed failure taxonomy, diagnosis, and root-cause attribution *(complete)*

- Hierarchical `FailureCode` taxonomy (`failure-taxonomy-v1`): 40+ codes across
  10 domains (planning, tool, recovery, state, safety, efficiency, agent,
  environment, evaluator, unknown).
- `FailureOrigin` attribution distinguishing agent / environment / provider /
  benchmark / evaluator causes.
- Five-level `FailureSeverity` driven by versioned `FailureSeverityPolicy`.
- `DiagnosticSignal` extraction separated from classification.
- `RootCauseAnalyzer` using journal order and evidence.
- `CriticalFailureStep` localisation.
- `EvidenceGraph` for auditable evidence.
- Versioned `FailureInstance` / `FailureReport` contracts.
- Deterministic explanation templates (no LLM dependency).
- Synthetic challenge set validating all failure detection paths.
- 570 tests, 90.24% branch coverage.

### Stage 4 — Calibrated/evidence-grounded judge and human validation *(engineering complete; human calibration pending)*

- Provider-neutral judge architecture.
- Ordinal 0–4 rubric with operational anchors for 6 subjective dimensions.
- `JudgeEvidencePackage` with no model/provider identity leakage.
- `FakeJudgeClient` and `ReplayJudgeClient` (deterministic, zero-network).
- Bias probe framework (position, verbosity, style, identity, evidence-order).
- `HybridEvaluationResult` preserving deterministic + judge as separate components.
- Human annotation workflow CLI with pseudonymous bundles.
- Inter-annotator agreement metrics (kappa, MAE, RMSE, Spearman).
- Annotation bundle generated and ready for real annotators.
- **Human calibration pending** — no fabricated labels.

### Stage 5 — Simulated transactional airline environment and side-effect safety *(planned)*

- Deterministic in-memory airline environment with explicit state machine.
- Simulated booking, hold, confirm, release, approval, and notification tools.
- Approval enforcement: scoped, payload-hashed, expiring.
- Idempotency key registry with conflict detection.
- Ambiguous commit scenario (mutation succeeds but response lost).
- 12 new transactional scenarios.
- Extended failure taxonomy for approval/idempotency failures.

### Stage 6 — Multi-model benchmark and evaluator-validity experiments *(planned)*

- Versioned `BenchmarkManifest`.
- Reproducible multi-agent comparison runner.
- Evaluator ablations comparing outcome-only, exact-sequence, constraint-graph, and diagnostics.
- Bootstrap confidence intervals for stochastic metrics.
- Benchmark results directory with manifest, summary, and methodology.

### Stage 7 — Public Benchmark V1 and reproducible release *(planned)*

- Offline `benchmark demo` command (no credentials, < 30 seconds).
- `benchmark verify-release` validation command.
- Portfolio-quality README.
- `CITATION.cff` and `CHANGELOG.md`.
- Version bump to 0.2.0.

## Architectural decision records

- `docs/adr/0001-python-project-foundation.md`
- `docs/adr/0002-contract-versioning.md`
- `docs/adr/0003-deterministic-fixture-provider.md`
- `docs/adr/0004-canonical-json.md`
- `docs/adr/0005-event-envelope-versioning.md`
- `docs/adr/0006-explicit-trajectories.md`
- `docs/adr/0007-contract-consolidation-and-evaluation-schema.md`
- `docs/adr/0008-trajectory-constraint-scoring.md`
- `docs/adr/0009-failure-taxonomy-and-diagnostics.md`

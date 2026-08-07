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

## Principles

1. **Contracts first.** All public types are strongly typed, versioned,
   provider-independent, and serialisable.
2. **Determinism by default.** Replay must be byte-identical given the same
   inputs, scenarios, and seeds.
3. **Strict typing.** Strict Pydantic v2, strict mypy, naive datetimes
   rejected, unknown fields rejected, `Any` avoided.
4. **Minimal runtime dependencies.** Phase 1 only requires Pydantic v2.
5. **No premature architecture.** FastAPI, SQLAlchemy, MCP SDK, Docker, and
   hosted model APIs are forbidden until their phase.
6. **Dependency direction is enforced.** Contracts → provider protocol →
   fixture provider. Nothing reaches upwards.

## Phases

### Phase 0 — Project definition and architecture *(complete)*

- Repository bootstrap.
- Mission and roadmap.
- Architectural decision records (ADRs).
- Baseline open-source files: licence, contributing, security, code of conduct.

Deliverables: this document, `README.md`, `LICENSE`, `CONTRIBUTING.md`,
`SECURITY.md`, `CODE_OF_CONDUCT.md`, `.gitignore`, `.editorconfig`,
`.gitattributes`, initial ADRs.

### Phase 1 — Contract foundation, deterministic fixture provider, and quality tooling *(complete)*

- uv-managed pure-Python package (`flight-agent-evaluator`) with `src/` layout.
- Strict Pydantic v2 contracts: aviation, booking/approval, providers,
  tools, traces, events, faults, scenarios, assertions, evaluation.
- `FlightProvider` `typing.Protocol`.
- Typed provider errors.
- `FixtureFlightProvider` using `importlib.resources`.
- Synthetic fixtures: delayed flight, alternative offers, not-found case, health response.
- ≥90% branch coverage (actual: 95.94%) with 215 focused, meaningful tests.
- mypy strict, Ruff (lint+format), pre-commit, CI on 3.11/3.12/3.13.
- `scripts/check.py` — 15-gate cross-platform quality runner.
- `canonical.py` — deterministic JSON canonicalisation and SHA-256 hashing.
- `ApprovalRequest.payload_hash` — computed from payload via `canonical_json()`.

### Phase 2 — Scenario execution, recording, replay and objective evaluation *(complete)*

- Scenario loader (versioned, strict).
- Deterministic execution and replay with seeded RNG.
- Chaos engine consuming fault specifications.
- Assertion evaluator with typed failure categories.
- Tool-call and event trace recording.
- End-to-end replay verification and CLI commands.

### Stage 2 — Trajectory Constraint Scoring Framework *(complete)*

- Pure data Pydantic contracts for trajectory expectation graphs, multiple valid solution paths, argument predicates, precedence, dependency, recovery, and safety rules.
- Deterministic bounded branch-and-bound matcher for optimal injective mapping under complexity bounds.
- Multi-dimensional scorecard output with node-by-node evidence attribution.
- Disruption read-only tools: `policy.get_rebooking_rules` and `itinerary.get_current_booking`.
- Benchmark expansion to 12 scenarios (scenarios 7-12) with public input/hidden expectation separation.
- CLI subcommands for trajectory validation, scoring, explanation, and benchmark suite validation.

### Stage 3 — Failure-mode classification and evidence attribution

- Failure-mode taxonomy and evidence attribution engine.

### Stage 4 — Calibrated LLM judge and human-labelled validation

- LLM judge calibration and human validation benchmarks.

### Stage 5 — Simulated approval, booking and idempotent mutation environment

- Simulated airline environment and idempotent state mutation support.

### Stage 6 — Multi-model benchmark and evaluator-validity experiments

- Cross-model benchmark evaluation and verifier fine-tuning.

### Stage 7 — Public held-out benchmark and reproducible results

- Public benchmark suite with canonical reference results.

## Architectural decision records

- `docs/adr/0001-python-project-foundation.md` — Python project foundation.
- `docs/adr/0002-contract-versioning.md` — Strict Pydantic contract versioning.
- `docs/adr/0003-deterministic-fixture-provider.md` — Deterministic fixture provider design.
- `docs/adr/0004-canonical-json.md` — Canonical JSON and approval hashing.
- `docs/adr/0005-event-envelope-versioning.md` — Event envelope versioning.
- `docs/adr/0006-explicit-trajectories.md` — Explicit trajectories vs hidden expectations.
- `docs/adr/0007-contract-consolidation-and-evaluation-schema.md` — Contract consolidation & evaluation schema.

## Open questions resolved during phases

*None yet.* As decisions land, they will be recorded as ADRs and reflected
here in a focused manner — the plan itself is not rewritten unnecessarily.

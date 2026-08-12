# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Stage 5 — Simulated Transactional Airline Environment & Side-Effect Safety**
  - `environment/contracts.py`: `BookingRecord`, `HoldRecord`, `ApprovalRequest`, `RebookingTransaction`, `IdempotencyRecord`.
  - `environment/state.py`: In-memory state machine transition validators (`UNBOOKED` -> `HOLD_PLACED` -> `REBOOKED`).
  - `environment/engine.py`: `SimulatedAirlineEnvironment` main engine.
  - `environment/approvals.py`: `ApprovalEngine` with scoped SHA-256 payload hash verification via `canonical_json()`.
  - `environment/idempotency.py`: `IdempotencyKeyRegistry` with conflict detection and cached replay.
  - `tools/booking_tools.py`: 7 simulated tools (`booking.get_current`, `booking.hold_alternative`, `booking.confirm_rebooking`, `booking.release_hold`, `approval.request`, `approval.get_status`, `notification.send_simulated`).
  - Extended failure taxonomy: `SAFETY.MISSING_APPROVAL`, `SAFETY.EXPIRED_APPROVAL`, `SAFETY.APPROVAL_SCOPE_MISMATCH`, `SAFETY.DUPLICATE_SIDE_EFFECT`, `TRANSACTION.IDEMPOTENCY_CONFLICT`, `TRANSACTION.AMBIGUOUS_COMMIT_UNRESOLVED`.
  - `resources/scenarios/stage-5/`: 12 transactional scenarios testing side-effect safety.
  - `resources/expectations/stage-5/`: 12 expectation graphs for Stage 5.
  - Documentation: `docs/architecture/stage-5-environment.md`, `docs/methodology/stage-5-environment.md`.

- **Stage 4 — Evidence-Grounded Judge & Human Validation Infrastructure**
  - `judges/contracts.py`: `JudgeCriterion` (6 criteria), `JudgeEvidencePackage` (no model ID), `JudgeResult`, `HybridEvaluationResult` with hard safety dominance.
  - `judges/rubric.py`: Operational anchors for 6 criteria across 5 score levels (0–4).
  - `judges/prompt.py`: System prompt builder with explicit warning that tool output is untrusted.
  - `judges/fake.py`: `FakeJudgeClient` for testing.
  - `judges/replay.py`: `ReplayJudgeClient` for zero-network CI execution matching on package digests.
  - `judges/metrics.py`: MAE, RMSE, Spearman, linear-weighted kappa, agreement rates.
  - `judges/bias.py`: Bias probe suite testing position, verbosity, and style stability.
  - `judges/calibration.py`: `compute_calibration_report` with honest pending status.
  - `annotation/contracts.py`: `AnnotationTask`, `AnnotationBundle` with tamper-detectable SHA-256 digest.
  - `annotation/bundle.py`: Bundle builder and freeze verification.
  - `validation/annotation-bundle-v1/bundle.json`: Packaged annotation bundle v1 (12 tasks).
  - CLI subcommands: `annotation validate`, `judge score`.
  - Documentation: `docs/architecture/stage-4-judge.md`, `docs/methodology/stage-4-judge-validation.md`, `docs/reports/stage-4-final.md`.

- Restored governance and documentation files: `CODE_OF_CONDUCT.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `.github/pull_request_template.md`.
- `docs/PROJECT_PLAN.md` — canonical stage roadmap with corrected stage numbering.
- `docs/README.md` — documentation index.
- `docs/adr/0001` through `0009` — architectural decision records.

### Fixed

- README stage numbering: failure taxonomy/diagnostics is Stage 3, not Stage 4.
- README status line updated to accurately reflect implementation state.

---

## [0.1.0] — 2026-08-11

### Stage 3 — Failure taxonomy and root-cause diagnostics (complete)

#### Added

- `evaluation/failure_codes.py` — hierarchical `FailureCode` taxonomy
  (`failure-taxonomy-v1`): 40+ codes across 10 domains.
- `evaluation/signals.py` — `DiagnosticSignal`, `EvidenceGraph`,
  `RootCauseAnalyzer`, `CriticalFailureStep`.
- `evaluation/diagnostics.py` — `DiagnosticsEngine`, `FailureInstance`,
  `FailureReport`.
- `evaluation/explanation_templates.py` — deterministic explanation templates.
- `evaluation/diagnostic_metrics.py` — aggregate diagnostic metrics.
- `FailureOrigin` attribution (agent / environment / provider / benchmark /
  evaluator).
- `FailureSeverityPolicy` with five severity levels and versioned SHA-256 digest.
- Synthetic challenge set (`tests/unit/evaluation/test_challenge_set.py`)
  validating all failure detection paths.
- CLI `trajectory` subcommand extensions for diagnostic reporting.

#### Tests

- 570 total tests (from 479).
- 90.24% branch coverage.

---

### Stage 2 — Trajectory constraint scoring (2026-08-06)

#### Added

- `contracts/trajectory_expectation.py` — `TrajectoryExpectation`,
  `ExpectationNode`, `ValidPath`, argument predicates, dependency rules.
- `evaluation/matcher.py` — `DeterministicBoundedMatcher`.
- `evaluation/trajectory_evaluator.py` — `TrajectoryEvaluator`.
- `evaluation/observation.py` — trajectory extraction from journal.
- `tools/policy.py`, `tools/itinerary.py` — disruption read-only tools.
- 6 new benchmark scenarios (scenarios 7–12) covering alternative paths,
  redundant lookups, ordering violations, security.
- 6 new expectation graphs in `resources/expectations/`.
- CLI `trajectory validate`, `trajectory score`, `trajectory explain`,
  `benchmark validate`, `benchmark run` subcommands.

---

### Stage 1 — Real model-driven agent (2026-08-02)

#### Added

- `agent/model_client.py` — `OpenAIResponsesModelClient`, `ReplayModelClient`.
- `agent/loop.py` — `ModelToolCallingAgent`.
- `agent/baselines.py` — `ScriptedOracleAgent`, `NaiveBaselineAgent`.
- `agent/security.py` — prompt-injection and leakage detection.
- SHA-256 model exchange fingerprinting for replay verification.

---

### Stage 0 — Evaluator/runtime correctness (2026-07-31)

#### Added

- Scenario loader (versioned, strict, BOM/duplicate-key/NaN rejection).
- Deterministic execution engine with seeded RNG.
- Hash-chained journal and recording store.
- Replay engine with divergence detection.
- Assertion evaluator with typed failure categories.
- CLI: `scenario`, `run`, `replay`, `verify`, `evaluate` subcommands.
- Fault injection engine.
- Pydantic v2 contracts: aviation, booking, providers, tools, events, faults.
- `FixtureFlightProvider` backed by `importlib.resources`.
- `canonical.py` — deterministic JSON + SHA-256.
- CI: Python 3.11/3.12/3.13, mypy strict, ruff, pre-commit, ≥90% coverage.

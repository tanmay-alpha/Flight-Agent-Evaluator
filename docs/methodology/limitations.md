# Limitations: what the evaluation does and does not prove

This page lists what the platform's results can and cannot support. Every item is traced to code on `main` as of 2026-11-05. Paths are relative to `src/flight_agent_evaluator/` unless stated otherwise.

Items marked **planned in v0.3 (in progress)** are being fixed in parallel work. They are not done until this page says so.

## What the evaluation does establish

- **Runs are deterministic.**
  - Run IDs are UUIDv5 values derived from scenario and seed (`runtime/ids.py`).
  - The clock is virtual, and the fixture provider is fixed.
  - The same scenario, seed and agent therefore produce the same journal.
- **Benchmark inputs are bound to digests.** Each manifest entry pins `scenario_sha256` and `expectation_sha256` (`benchmarks/manifest.py:39-42`). The loader rejects bytes that don't match (`benchmarks/loader.py:164,183,282,309`).
- **Scoring is reproducible.** Given a journal and an expectation, the score comes from fixed rules (`evaluation/trajectory_evaluator.py:325-494`).
- **Authored scenarios and their expectations are consistent.** Each scenario's scripted trajectory satisfies the expectation written for it: `scripted-oracle` scores 24/24 (`results/benchmark-v1/README.md:21`). This is a consistency check on the benchmark itself, not a measurement of any agent.

## What it does not establish

### 1. The environment is synthetic
- **Flight data:** the only flight data provider is `FixtureFlightProvider` (`providers/fixture.py:407`), which serves packaged JSON. There are no live provider adapters and no HTTP client in `providers/`.
- **Airline back end:** `SimulatedAirlineEnvironment` is an in-memory model.
- **Offer inventory:** offers are copied from the `booking.hold_alternative` arguments in the scenario's own scripted trajectory (`environment/engine.py:228-244`).
- **Initial state:** `BenchmarkScenario.initial_state` (`contracts/scenarios.py:64`) is not read by `from_scenario` (`environment/engine.py:218-245`).
- **Approvals are not human-in-the-loop.**
  - The approve/deny/expire decision comes from a hardcoded table keyed by scenario ID (`environment/engine.py:98-166`).
  - Unknown scenario IDs fall back to `APPROVED` (`environment/engine.py:56,92,166`).
  - Fail-closed approvals are **planned in v0.3 (in progress)**.
- **Expiry and lost responses are flags, not elapsed time:**
  - `hold_expired`, `response_lost_on_confirm` and `alternative_disappears` (`environment/engine.py:93-95`);
  - `approval-expires` is created already `EXPIRED` (`environment/engine.py:111-115`).
- **Fault injection ignores the seed and call sequence** (`engine/fault_engine.py:113`, `del sequence`). Faults fire on deterministic per-tool counters.

### 2. The reference agents are scripted
- **The canonical benchmark has run three scripted policies and no model** (`results/benchmark-v1/README.md:6,28`):
  - `scripted-oracle` replays the scenario's own trajectory (`engine/benchmark.py:293-309`) and ignores the task (`agent/baselines.py:45`, `noqa: ARG002`);
  - `naive-baseline` calls only `flight.get_status` and `flight.search_flights` (`agent/baselines.py:146-260`);
  - `no-op-baseline` makes no calls and stops with `ERROR` (`agent/baselines.py:276-301`).
- **No LLM agent run has been recorded in this repository.** `agent/model_client.py:33` defines `OpenAIResponsesModelClient`. A working, recorded LLM adapter is **planned in v0.3 (in progress)**.
- **The 100% safety-pass rate is untested.** No baseline attempts a mutation, so the rate comes from agents that never act. Only 3 of 24 expectations declare `safety_constraints` (`bwi-mco-forbidden-mutation`, `jfk-lhr-delay`, `prompt-injection-untrusted-output`).
- **The tool allowlist leaks the golden trajectory.** The allowlist given to the agent is the set of tools used in the scenario's scripted trajectory (`engine/benchmark.py:193-198`, `engine/runner.py:135-137`). An agent therefore learns which tools the reference solution uses.

### 3. The evaluator is rule-based and has not been validated against labels
- **How it works:**
  - Safety checks are glob, substring and selector rules (`evaluation/trajectory_evaluator.py:197-321`).
  - Matching is an exhaustive depth-first search capped at 10 candidates per node and 10,000 states (`evaluation/matcher.py:215,236,313-339`).
  - "Root cause" is assigned from failure-code prefix and journal order (`evaluation/signals.py:754-792`). The code's own rationale string says "direct causality inferred by journal order" (`:784`).
- **Known gaps:**
  - The composite score ignores safety (`trajectory_evaluator.py:427-436`), so an unsafe run can still score close to 1.0. Only `overall_pass` fails.
  - `recovery_score` is hard-coded to `1.0` (`trajectory_evaluator.py:559`).
  - A dependency constraint is met if the required node is satisfied, with no check of order or data flow (`evaluation/matcher.py:465-474`).
  - Truncating to 10 candidates by tool name happens before arguments are checked (`matcher.py:236`), so a correct call that comes after 10 near-misses can be missed.
  - The benchmark's evaluator-error rate only counts the literal `"evaluator_error"` (`benchmarks/engine.py:233-237`), but the evaluator emits `no_applicable_path` / `evaluator_complexity_limit` (`trajectory_evaluator.py:352,369`). The reported 0.0% can therefore never be anything else.
  - Path-level forbidden actions are checked on every applicable path, not just the selected one (`trajectory_evaluator.py:302-321`).
- **No labelled false-positive or false-negative rates exist.** The checks in place are hand-written invariant tests (`tests/unit/evaluation/test_trajectory_validity_counterexamples.py`) and a developer-labelled diagnostics challenge set (`tests/unit/evaluation/test_challenge_set.py`).
- **In progress:** evaluator safety-check fixes and an evaluator validation harness are **planned in v0.3 (in progress)**.

### 4. The judge is a placeholder
- **`ReplayJudgeClient` has nothing to replay.** It only replays recorded exchanges, and no exchange manifest is committed.
- **Live judging is not implemented.** `JudgeMode.LIVE`/`RECORD` exist only as enum values (`judges/contracts.py:303-307`), and no client implements them.
- **`FakeJudgeClient` gives the same score to everything.** It returns score 2 on every criterion with `confidence="high"`, and labels its result `mode=JudgeMode.REPLAY` (`judges/fake.py:65-85`). It is the default for `flight-evaluator judge score` (`--mode` defaults to `fake`, `cli/main.py:1244-1246,727-730`).
- **The judge is not part of evaluation.** Outside `judges/`, the only importers are the CLI and the annotation bundle builder (`cli/main.py:43`, `annotation/bundle.py:14`).
- **In progress:** labelling fake output with its own `FAKE` mode and the judge contract changes are **planned in v0.3 (in progress)**. See [`judge-validation.md`](judge-validation.md).

### 5. There are no human labels
- **The annotation bundle is empty.** `validation/annotation-bundle-v1/bundle.json` has 12 tasks, every one with `annotation_count: 0`, and `annotation_status: "pending"`.
- **No agreement metric has been computed on real data.**
  - `judges/metrics.py` implements MAE, RMSE, Spearman, linearly weighted κ and agreement rate.
  - It does not implement Krippendorff's α.
  - `compute_calibration_report` returns `ENGINEERING_COMPLETE_HUMAN_CALIBRATION_PENDING` whatever the agreement (`judges/calibration.py:156-170`). Threshold-based calibration statuses are **planned in v0.3 (in progress)**.
- **Collecting human labels is not code work.** No annotation has been collected, and none is claimed.

### 6. The hash chain is unkeyed
- **The journal hash is plain SHA-256.** Each entry's hash is SHA-256 over its canonical JSON plus `prev_hash` (`recording/journal.py:32-39`). The module itself says: "No cryptographic authentication is provided" (`recording/journal.py:9-10`).
- **Bundle digests are also unkeyed.** The bundle manifest's `journal_bytes_sha256`/`metadata_bytes_sha256` are plain digests (`recording/contracts.py:144-178`).
- **What this protects against:** the chain detects accidental edits and naive tampering.
- **What it does not protect against:** an adversary who edits a journal and recomputes every hash and manifest digest. Nothing is signed or MAC'd.

### 7. Replay checks structure, not values
- **Tool output values are never compared.** The tool executor journals tool output under `"result"` (`engine/tool_executor.py:355`). Replay projection and comparison read `"value"` (`replay/projection.py:110`, `replay/comparator.py:189-190`). Both sides are therefore `None`.
- **What `behaviour_verified` currently means:** the event types, call arguments and result statuses matched.
- **Provenance checks only the scenario digest.** Replay re-checks the scenario digest (`replay/provenance.py:123-157`), but not the expectation digest stored in the bundle.
- Comparing replay values is **planned in v0.3 (in progress)**.

### 8. The corpus is small and narrow
- **Size:** 24 scenarios (12 read-only, 12 transactional) under `resources/scenarios/`.
- **Single path:** only `ord-sea-dual-order` declares more than one valid path.
- **Missing scenario types:** no scenario models multi-leg journeys, budgets, weather diversions or misconnections.

# Limitations: what the evaluation does and does not prove

This page lists what the platform's results can and cannot support. Every item is traced to code on branch `release/v0.4.0` (package version 0.4.0). Paths are relative to `src/flight_agent_evaluator/` unless they start with `results/`, `validation/` or `tests/`.

## What the evaluation does establish

- **Runs are deterministic.**
  - IDs are UUIDv5 values derived from scenario, version, seed, record type and sequence (`runtime/ids.py:48-49`).
  - The clock is virtual, and the default provider is the fixture provider (`engine/runner.py:46-47`).
- **Benchmark inputs are bound to digests.**
  - Each manifest entry pins `scenario_sha256` and `expectation_sha256` (`benchmarks/manifest.py:41,43`).
  - The loader rejects resource bytes that don't match (`benchmarks/loader.py:97-106,164,183,282,309`).
- **Scoring is reproducible.** Given a journal and an expectation, scores come from fixed rules (`evaluation/trajectory_evaluator.py`, `evaluation/journal_safety.py`).
- **The evaluator catches the injected defects it has been tested against.** `validation/evaluator-validation-v1/report.md` runs 141 construction-labelled perturbations of the golden trajectories through the real benchmark pipeline. Results:
  - `task_failure`: recall 0.989 and FP rate 0.000 overall.
  - `safety_violation`: precision 0.909, recall 1.000 and FP rate 0.036 overall.
  - 4 cases are misclassified, and the report lists them.
- **Authored scenarios and their expectations are consistent.** `scripted-oracle` passes 24/24 (`results/benchmark-v1/README.md`). This is a check on the benchmark itself, not a measure of agent capability.

## What it does not establish

### 1. The environment is synthetic
- **Flight data:** the only flight data provider is `FixtureFlightProvider` (`providers/fixture.py:407`), which serves packaged JSON. There are no live provider adapters and no HTTP client in `providers/`.
- **Airline back end:** `SimulatedAirlineEnvironment` is an in-memory model. Each transactional scenario declares its bookings, offers and approval decision in an `environment` block (`contracts/scenarios.py:73-86,154`), and the environment is built from that block only (`environment/engine.py:127-132`).
- **Approvals are scenario-configured, not human-in-the-loop.**
  - Every approval request gets the scenario's configured `approval_decision` (`environment/engine.py:394`).
  - A scenario that configures no decision fails closed to `DENIED` (`environment/engine.py:53-54,105-109`).
  - No human or queue is involved.
- **Most expiry and loss conditions are flags, not elapsed time.**
  - `hold_expired` back-dates the hold (`environment/engine.py:274-279`).
  - `alternative_disappears` marks the offer unavailable right after the hold (`:306-307`).
  - `response_lost_on_confirm` raises an ambiguous-commit error once, after the commit (`:572-574`).
  - An approval configured as `"expired"` is expired from the moment it is created.
  - The virtual clock moves only on a `delayed_response` fault (`engine/tool_executor.py:256-258`).
- **Fault injection uses neither the seed nor the call sequence** (`engine/fault_engine.py:113`, `del sequence`). Faults fire on deterministic per-tool counters. Only `jfk-lhr-timeout-recovery` declares a fault.
- **Scenario logical time limits are enforced on the virtual clock.** The benchmark runner passes `logical_time_limit_ns = context.time_limit_seconds * 1_000_000_000` to the executor (`engine/benchmark.py:333`), which terminates with `time_limit_exceeded` if elapsed logical time exceeds the scenario budget (`engine/tool_executor.py:194-205`).

### 2. The reference agents are scripted, and no real model run is committed
- **The canonical bundle `results/benchmark-v1` contains four scripted policies** (`results/benchmark-v1/README.md`):
  - `scripted-oracle` replays the scenario's golden trajectory (`engine/benchmark.py:286-302`);
  - `naive-baseline` makes read-only lookups only (`agent/baselines.py:129-273`);
  - `no-op-baseline` makes no calls and stops with `ERROR` (`agent/baselines.py:275-301`);
  - `unsafe-baseline` is a negative control. It confirms with a self-issued approval ID, ignores denials and always claims success (`agent/baselines.py:309,320-501`).
- **A real LLM path exists but has never been run against a real model here.**
  - `OpenAIChatCompletionsClient` (`agent/model_client.py:158`) runs the LLM agent `ModelToolCallingAgent` (`agent/loop.py:33`) in `live` or `record` mode.
  - `ReplayModelClient` (`agent/model_client.py:370`) replays recorded exchange manifests.
  - Tool names are mapped `.` ↔ `__` for the provider (`agent/tool_names.py:14-38`).
- **No recorded model-exchange manifest from a real model is committed.** The only end-to-end test uses a fake OpenAI-compatible server (`tests/e2e/test_model_agent_replay.py:1-5`).
<!-- live-model findings inserted by lead -->
- **The 100% safety-pass rates of the safe agents show that they never attempted an unsafe action.** They do not show that the agents handled unsafe situations well:
  - `naive-baseline` never mutates, and `no-op-baseline` makes no calls.
  - The safety checks *are* exercised by `unsafe-baseline` (0.0% safety pass) and by the evaluator-validation operators.
- **Golden trajectories only take the safe path.** Each transactional scenario sets up its named condition in the `environment` block, but its golden trajectory avoids it. For example:
  - `payload-changes-after-approval` re-approves the second offer before confirming;
  - `hold-expires` releases the hold instead of confirming.

  The unsafe branches are reached only by `unsafe-baseline` and by the validation operators.

### 3. The evaluator is rule-based, and has been validated only on synthetic labels
- **How it works:**
  - Journal safety checks are rules over tool calls, results and approval records (`evaluation/journal_safety.py:341-415`).
  - Success-claim detection is regex-based (`evaluation/claims.py:45-182`).
  - Matching is a bounded branch-and-bound search with 10 candidates per node and 10,000 states (`evaluation/matcher.py:226,264,419-431`).
  - "Root cause" is assigned from failure-code prefix and journal order. The code's own rationale string says "direct causality inferred by journal order" (`evaluation/signals.py:681-776,743`).
- **What has been validated, and how.** The validation harness (`evaluation/validation/`, `flight-evaluator evaluator validate`) builds its labels **synthetically by construction**:
  - each case is a golden trajectory with one deterministic perturbation (`evaluation/validation/operators.py:1-7,59-69`);
  - no human labelled anything;
  - the results say nothing about accuracy on real agent trajectories, and the clean controls assume the golden trajectories are correct (`validation/evaluator-validation-v1/report.md`).
- **Errors in the committed report** (`validation/evaluator-validation-v1/report.md`). It records 3 safety false positives, all from `drop_required_step` or `corrupt_key_argument` perturbations on `duplicate-rebooking-attempt` / `mutation-success-response-lost`. It also records 1 task false negative: a `false_success_claim` on `duplicate-rebooking-attempt` that was not detected.
- **Held-out generalization limits (unmarked injections and lexical claims):**
  - **Injection attribution is weak for unmarked or paraphrased injections.** The untrusted-output tracker relies on recognizable directive action vocabulary in tool outputs (`evaluation/claims.py:187-222`). Injections that omit overt markers, embed instructions inside indirect narratives, or paraphrase tasks without directive verbs may not be attributed to `SAFETY.UNTRUSTED_OUTPUT_FOLLOWED`.
  - **False-success detection is lexical.** Claim detection in `evaluation/claims.py:45-184` relies strictly on English regular expressions for completed actions (`_CLAIM_PATTERNS`) and negative hedges (`_NEGATION_RE`). It has no semantic inference engine: paraphrased claims outside these patterns are missed (false negatives), claims in other languages are unsupported, and subtle hallucinations without standard action verbs are invisible to the detector.
- **Remaining evaluator gaps:**
  - Claims are backed by journal evidence (successful calls or read-backs), not directly by deep external database state. A `refund` claim can never be backed, because no refund tool exists in the default toolset (`evaluation/journal_safety.py:115-123`).
### 4. The judge is a placeholder
- **`FakeJudgeClient` returns placeholder scores** (default 2) with `mode=fake`, `confidence="low"` and an explicit FAKE warning (`judges/fake.py:31,77,86-87`).
- **`ReplayJudgeClient` has nothing to replay.** It needs recorded exchanges, and none are committed.
- **Live judging is not implemented.** `JudgeMode.RECORD`/`LIVE` are reserved, and no client implements them (`judges/contracts.py:297-311`).
- **The judge is not part of evaluation.** Outside `judges/`, only the CLI and the annotation bundle builder import it (`cli/main.py:47-51`, `annotation/bundle.py:14`). See [`judge-validation.md`](judge-validation.md).

### 5. There are no human labels
- **The annotation bundle is a template.** `validation/annotation-bundle-v1/bundle.json` has 12 tasks with `annotation_count: 0`, `annotation_status: "template"`, and placeholder responses.
- **No calibration has been run.** `compute_calibration_report` can report `insufficient_data`, `below_threshold` or `meets_threshold`, and it rejects fake-mode judge results (`judges/calibration.py:75-85,172-180`). It has never been run on real annotations.
- **No Krippendorff's α.** `judges/metrics.py` implements MAE, RMSE, Spearman, linearly weighted κ and agreement rate, but not α.

### 6. The hash chain is unkeyed
- **The journal hash is plain SHA-256.** Each entry's hash is SHA-256 over its JSON canonicalisation plus `prev_hash` (`recording/journal.py:27-39`). The module itself says: "No cryptographic authentication is provided" (`recording/journal.py:9-10`).
- **Bundle digests are also unkeyed.** The bundle manifest's digests are plain SHA-256 values (`recording/contracts.py:144-178`).
- **What this protects against:** accidental edits and naive tampering.
- **What it does not protect against:** an adversary who edits a journal and recomputes every hash and manifest digest. Nothing is signed or MAC'd.

### 7. Replay compares values, but provenance and agent coverage are narrow
- **Tool output values are compared.** Projection `semantic-events-v2` keeps tool-result `result` values (`replay/projection.py:114-123`), and the comparator reports `TOOL_RESULT_VALUE_MISMATCH` when they differ (`replay/comparator.py:189-199`).
- **Provenance re-checks only the scenario digest.** `replay/provenance.py:120-157` does not compare the expectation, fixture, agent-configuration or model-exchange digests in the bundle against anything.
- **Some agents cannot be re-executed.** Only scripted, naive and model agents can be (`replay/provenance.py:175-189`). `no-op-baseline` and `unsafe-baseline` recordings return `ReplayUnavailableError`.
- **Recordings are separated by agent configuration.** Run IDs include the agent identity and `configuration_digest` (`engine/benchmark.py:288-295`), preventing different agents from colliding. Re-executing the *exact same* agent, configuration and scenario will deterministically overwrite earlier files.

### 8. The corpus is small and narrow
- **Size:** 24 scenarios (12 read-only, 12 transactional) under `resources/scenarios/`.
- **Single path:** only `ord-sea-dual-order` declares more than one valid path.
- **Missing scenario types:** no scenario models multi-leg journeys, budgets, weather diversions or misconnections.

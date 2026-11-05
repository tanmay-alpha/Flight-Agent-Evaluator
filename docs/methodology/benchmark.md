# Benchmark Methodology and Manifest Integrity

Paths are relative to `src/flight_agent_evaluator/`. See [`limitations.md`](limitations.md) for what the benchmark does and does not prove.

## What the corpus contains

Benchmark V1 has 24 scenarios, each paired with an authored expectation. Scenarios are in `resources/scenarios/` and expectations in `resources/expectations/`.

**Read-only (12):**
- `lax-sfo-ontime`
- `jfk-lhr-delay`
- `jfk-lhr-timeout-recovery`
- `atl-mia-wrong-arguments`
- `bwi-mco-forbidden-mutation`
- `clt-phx-retry-dependency`
- `dfw-den-no-alternatives`
- `iad-ord-redundant-lookup`
- `ord-sea-dual-order`
- `prompt-injection-untrusted-output`
- `sfo-bos-optional-lookup`
- `unknown-flight-lookup`

These cover:
- flight-status lookups for on-time, delayed and unknown flights;
- searching for alternatives;
- one injected timeout fault (`jfk-lhr-timeout-recovery`);
- argument, ordering and redundancy checks;
- one prompt-injection fixture.

**Transactional (12, in `transactional/`):**
- `approval-granted`
- `approval-denied`
- `approval-expires`
- `approval-wrong-itinerary`
- `mutation-without-approval`
- `payload-changes-after-approval`
- `constraint-changes-after-approval`
- `duplicate-rebooking-attempt`
- `hold-expires`
- `idempotent-retry-after-timeout`
- `mutation-success-response-lost`
- `alternative-disappears-before-confirm`

These cover the hold → approval → confirm workflow in the simulated environment.

**What the corpus does not contain:**
- multi-leg journeys, budget limits, weather diversions, misconnections, cancellations by the agent, or seat-class constraints;
- multiple valid paths, except in `ord-sea-dual-order`, the only expectation with more than one path.

**Some transactional scenarios don't reach the condition they are named after.** Approval outcomes come from a per-scenario table (`environment/engine.py:98-166`), not a human. Examples:
- `approval-expires` starts with its approval already `EXPIRED` (`:111-115`); no time passes.
- The `payload-changes-after-approval`, `constraint-changes-after-approval` and `duplicate-rebooking-attempt` trajectories never send a second or modified confirmation.

Making each scenario exercise its named condition is **planned in v0.3 (in progress)**.

## Manifest binding

- **Pinned files.** Each manifest entry pins `scenario_path`, `scenario_sha256`, `expectation_path` and `expectation_sha256` (`benchmarks/manifest.py:39-42`).
- **Byte check at load.** `benchmarks/loader.py` checks the bytes of both files against those digests before it builds cases (`:164,183,282,309`).
- **Consistency checks.** `BenchmarkCorpusValidator` (`benchmarks/validator.py:62`) checks that scenario and expectation IDs match the manifest entry (`:360-380`).
- **Per-case result digest.** Each `BenchmarkCaseResult` carries a `semantic_result_digest` (`benchmarks/results.py:168-193`). It covers the manifest digest, both resource digests, agent identity, seed, outcome fields, failure codes, `run_id` and `journal_digest`.

## Run journal

The benchmark runner (`engine/benchmark.py`) writes these events to a SHA-256 hash-chained journal:

| Event | What it records |
| --- | --- |
| `run_started` | `scenario_id`, `agent_id`, `start_time` (`:281-291`) |
| `tool_call` / `tool_result` | Journalled by `ToolExecutor` for each call |
| `final_response` | `response`, `stop_reason`, `tool_call_count` (`:323-338`) |
| `run_completed` | `task_success`, `safety_pass`, `overall_pass`, `composite_score` (`:380-391`) |

`journal_digest = journal.final_digest()` (`:402`) is copied into the case result and included in its `semantic_result_digest`.

The chain is **unkeyed** SHA-256 (`recording/journal.py:9-10`). It detects accidental edits, but not an adversary who rewrites the entries and recomputes the hashes. See [`limitations.md`](limitations.md#6-the-hash-chain-is-unkeyed).

## Scoring rules that matter for the leaderboard

See [`scoring.md`](scoring.md). Two rules matter most here:

- If outcome assertions exist but the journal has no timestamps, `outcome_score` is 0.0 (`evaluation/trajectory_evaluator.py:340-341`).
- If `required_recall == 0` and the path has required nodes, the argument, dependency and ordering components are 0.0 (`:411-414`).

The **efficiency** component is not zeroed: an agent that makes no calls still gets efficiency 1.0. Outcome assertions that hold without any agent action also count. This is why `no-op-baseline` averages 0.250 and not 0.

## Recorded baseline results (`results/benchmark-v1/`)

The committed run used **three scripted policies and no language model** (`results/benchmark-v1/README.md:6,28`):

| Agent policy | What it actually does | Task success | Safety pass | Avg `overall_score` | Evaluator errors |
|---|---|---|---|---|---|
| `scripted-oracle` | Replays the scenario's own scripted trajectory (`engine/benchmark.py:293-309`) | 100.0% (24/24) | 100.0% | 0.987 | 0.0% |
| `naive-baseline` | Regex flight lookup, `flight.get_status` (one retry), `flight.search_flights`; never mutates (`agent/baselines.py:146-260`) | 41.7% (10/24) | 100.0% | 0.644 | 0.0% |
| `no-op-baseline` | Makes no calls; stops with `ERROR` (`agent/baselines.py:276-301`) | 0.0% (0/24) | 100.0% | 0.250 | 0.0% |

**How to read these numbers:**
- **The oracle's 100%** shows that each scripted trajectory satisfies the expectation written for it. That is a check that the corpus is self-consistent, not a measurement of an agent.
- **The 100% safety-pass rate is untested.** None of these policies attempts a mutation, and only 3 of 24 expectations declare `safety_constraints`.
- **The 0.0% evaluator-error rate is structural.** The aggregate counts only the literal `"evaluator_error"` (`benchmarks/engine.py:233-237`), while the evaluator emits `no_applicable_path` / `evaluator_complexity_limit`.
- **The order oracle > naive > no-op is what you would expect from scripted policies.** It does not show that the benchmark rewards domain reasoning in a model.

Recorded runs of a working LLM agent are **planned in v0.3 (in progress)**.

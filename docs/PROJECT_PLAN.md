# Flight Agent Evaluator — Project Status and Roadmap

## Mission

Flight Agent Evaluator is an open-source evaluation, replay and diagnostics platform for tool-using agents in a simulated airline-disruption domain.

## Scope and non-goals

- **Not a consumer chatbot.** The project is about evaluation, benchmarking and failure diagnostics.
- **Not a live booking tool.** It runs against an in-memory simulated environment with fixture flight data. No real reservations or payments are made.
- **Provider-neutral contracts.** The evaluation contracts don't depend on any model vendor.

---

## Status of each capability (v0.4.0, audited 2026-11-06)

"Implemented" means the code exists and is tested. It does not mean the capability has been validated against real agents or human labels. See [`methodology/limitations.md`](methodology/limitations.md). Paths are relative to `src/flight_agent_evaluator/`.

| Capability | Status | What is actually there |
| --- | --- | --- |
| **Contract foundation** | Implemented | Pydantic v2 contracts for entities, scenarios (including the `environment` block), events, expectations, scorecards, failure details, and model exchanges. Artifacts use `schema_version = "0.4.0"`. Authored expectations are required unless explicitly opted into via `allow_development_expectation`. |
| **Transactional environment** | Implemented | Each scenario's `environment` block sets the inventory and the approval decision. An unconfigured decision fails closed to `DENIED` (`environment/engine.py:53-54,105-109`). The tool executor enforces strict JSON, 64 KiB argument bounds, non-finite float rejection (`_finite_json`), argument validation strictly before fault injection, cancellation journaled as an unknown outcome, and journaling of over-budget calls (`_budget_exhausted`). Golden trajectories take only the safe path; unsafe branches are exercised by `unsafe-baseline` and the validation operators. |
| **Tool allowlist** | Implemented | `default_allowed_tools` uses the scenario's explicit list or all tools for its mode, never the golden trajectory (`tools/base.py:191-209`). |
| **Trajectory evaluation** | Implemented, validated on synthetic labels | Journal safety checks run on every run: approvals, denied attempts, duplicate side effects, unbacked success claims (excluding read-outs, questions/offers, and third-party actions) and untrusted instructions (`evaluation/journal_safety.py`, `evaluation/claims.py`). Bounded branch-and-bound matcher (`evaluation/matcher.py`) with tie-break order (passing, highest composite, ascending path_id), exclusive occurrence bounds per node (repeats up to `max_occurs` are free), fail-closed `numeric_range` and `datetime_range` operators, and order/success/binding checks on dependency constraints. Six-component composite score with absent assertions yielding `outcome_score = 0.0` and `outcome_evaluated = False` (does not fail path), empty trajectories receiving efficiency `0.0`, all-zero weights rejected, and reported score capped at 0.0 for unsafe runs (`engine/benchmark.py:459`). Validation v2 (`evaluation/validation/`) introduces a dev/held-out split (~60/40 via unsigned SHA-256 % 10), contamination guard with isolated held-out phrasing templates and dev-report fingerprint checks, Wilson 95% CIs, and small-n point suppression below n < 10. |
| **Failure diagnostics** | Implemented | Rule-based failure codes across 11 prefixes, a versioned severity policy, template explanations, and structured `failure_details`. Root causes are chosen by journal-order heuristics, not causal analysis (`evaluation/signals.py:681-776`). Agent exceptions yield `AGENT.EXECUTION_ERROR` per case while the benchmark suite continues uninterrupted (`engine/benchmark.py:382-403, 500-508`). |
| **Replay and tamper detection** | Implemented, with limits | Unkeyed SHA-256 hash chain plus bundle manifest. Model provenance and `configuration_digest` prevent run collisions. Re-execution is compared on `semantic-events-v2`, including tool result values. Exact replay of malformed calls (`raw_arguments`, `arguments_error`). Secret-bearing exchange manifests are refused (`agent/security.py`: `sk-` left boundary, custom secrets ≥ 12 characters). Verify exits 0, 1 or 3 (`cli/main.py`). |
| **External trace evaluation** | Implemented | `flight-evaluator trace evaluate` re-executes external traces through `ToolExecutor` with strict containment (rejecting absolute paths, Windows drive letters, parent traversal `..`, and symlink ancestors) and optional `--allow-root` (`traces/`). |
| **Packaged distribution & SDK** | Implemented | Wheel with built-in scenarios (24), expectations (24) and manifests. Supported public SDK surface is exported in `flight_agent_evaluator.__all__`. Runs offline. |
| **LLM agent** | Implemented, not demonstrated | `ModelToolCallingAgent` runs through `OpenAIChatCompletionsClient` in live or record mode, or through `ReplayModelClient` with recorded exchange manifests (`agent/loop.py`, `agent/model_client.py`). Enforces per-call model timeouts. No real model run is committed. |
| **Benchmarks & tooling** | Implemented | Multi-agent execution, `benchmark compare` for regression gating, gating flags (`--fail-under-success`, `--require-safety`, `--baseline`, `--max-regression`) with typed exit codes (0 pass, 1 gate failed, 2 input error, 3 evaluator error), and annotation workflow tools (`annotation workflow -- export|validate|agreement|adjudicate|compare-evaluator`). |
| **Qualitative judge** | Placeholder | Contracts, a 0–4 rubric, a fake client (`mode=fake`) and a replay client, plus calibration statuses. There is no live client, no recorded exchanges and 0 human annotations. The judge is not part of evaluation. |
---

## Committed evidence

- **`results/benchmark-v1/`.** 96 runs: 24 scenarios × `scripted-oracle`, `naive-baseline`, `no-op-baseline` and `unsafe-baseline`. Values from `summary.json`:
  - `task_success_rate` 0.3541666666666667
  - `safety_pass_rate` 0.75
  - `evaluator_error_rate` 0.0
  - `average_overall_score` 0.4728356481481482

  See [`methodology/benchmark.md`](methodology/benchmark.md).
- **`validation/evaluator-validation-v1/report.md`.** 141 construction-labelled cases. These are synthetic labels, not human annotations.

---

## Current scientific limitations

The full list is in [`methodology/limitations.md`](methodology/limitations.md). In short:

1. **The environment is synthetic.** Fixture data, simulated state, and approvals set by each scenario's configuration.
2. **The reference agents are scripted.** No model has been evaluated, and no real LLM run is committed.
3. **The evaluator is rule-based.** It has been validated only on synthetic, construction-labelled perturbations.
4. **The judge is a placeholder.** The fake client returns placeholder scores.
5. **There are no human labels.** The annotation bundle is a template with 0 annotations.
6. **The hash chain is unkeyed.** It detects accidental edits, not an adversary who recomputes the hashes.

---

## Next

- Recorded runs of a real LLM agent.
- Human annotations and a judge calibration run.
- Scenarios whose recorded agents actually take the unsafe branches, alongside the safe golden paths.
- Provenance checks for the expectation, fixture and model-exchange digests.

## Future research directions

- Multi-passenger and split-itinerary rebooking scenarios.
- Checking that constraint graphs are satisfiable before a benchmark runs.
- Multilingual passenger dialogue.

# Flight Agent Evaluator — Project Status and Roadmap

## Mission

Flight Agent Evaluator is an open-source evaluation, replay and diagnostics platform for tool-using agents in a simulated airline-disruption domain.

## Scope and non-goals

- **Not a consumer chatbot.** The project is about evaluation, benchmarking and failure diagnostics.
- **Not a live booking tool.** It runs against an in-memory simulated environment with fixture flight data. No real reservations or payments are made.
- **Provider-neutral contracts.** The evaluation contracts don't depend on any model vendor.

---

## Status of each capability (v0.3.0, audited 2026-11-06)

"Implemented" means the code exists and is tested. It does not mean the capability has been validated against real agents or human labels. See [`methodology/limitations.md`](methodology/limitations.md). Paths are relative to `src/flight_agent_evaluator/`.

| Capability | Status | What is actually there |
| --- | --- | --- |
| **Contract foundation** | Implemented | Pydantic v2 contracts for entities, scenarios (including the `environment` block), events, expectations, scores and model exchanges. |
| **Transactional environment** | Implemented | Each scenario's `environment` block sets the inventory and the approval decision. An unconfigured decision fails closed to `DENIED` (`environment/engine.py:53-54,105-109`). Golden trajectories take only the safe path; unsafe branches are exercised by `unsafe-baseline` and the validation operators. |
| **Tool allowlist** | Implemented | `default_allowed_tools` uses the scenario's explicit list or all tools for its mode, never the golden trajectory (`tools/base.py:191-209`). |
| **Trajectory evaluation** | Implemented, validated on synthetic labels only | Journal safety checks run on every run: approvals, denied attempts, duplicate side effects, unbacked success claims and untrusted instructions (`evaluation/journal_safety.py`, `evaluation/claims.py`). Other parts: a branch-and-bound matcher (`evaluation/matcher.py`); a six-component composite, with the reported score capped at 0.0 for unsafe runs (`engine/benchmark.py:372`); and recovery scored from `recovery_constraints`. `validation/evaluator-validation-v1/report.md` reports `task_failure` recall 0.989 and `safety_violation` precision 0.909 on construction-labelled perturbations. |
| **Failure diagnostics** | Implemented | Rule-based failure codes (52), a versioned severity policy, and template explanations. Root causes are chosen by journal-order heuristics, not causal analysis (`evaluation/signals.py:681-776`). |
| **Replay and tamper detection** | Implemented, with limits | Unkeyed SHA-256 hash chain plus bundle manifest. Re-execution is compared on `semantic-events-v2`, including tool result values. Verify exits 0, 1 or 3 (`cli/main.py:285-306`). Provenance re-checks only the scenario digest; no-op and unsafe agents cannot be re-executed. |
| **External trace evaluation** | Implemented | `flight-evaluator trace evaluate` re-executes and scores tool-call traces from other frameworks (`traces/`). |
| **Packaged distribution** | Implemented | Wheel with built-in scenarios, expectations and manifests. Runs offline. |
| **LLM agent** | Implemented, not demonstrated | `ModelToolCallingAgent` runs through `OpenAIChatCompletionsClient` in live or record mode, or through `ReplayModelClient` with recorded manifests (`agent/loop.py:33`, `agent/model_client.py:158,370`). No real model run is committed. |
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

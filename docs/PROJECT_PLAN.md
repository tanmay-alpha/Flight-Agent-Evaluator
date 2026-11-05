# Flight Agent Evaluator — Project Status and Roadmap

## Mission

Flight Agent Evaluator is an open-source evaluation, replay and diagnostics platform for tool-using agents in a simulated airline-disruption domain.

## Scope and non-goals

- **Not a consumer chatbot.** The project is about evaluation, benchmarking and failure diagnostics.
- **Not a live booking tool.** It runs against an in-memory simulated environment with fixture flight data. No real reservations or payments are made.
- **Provider-neutral contracts.** The evaluation contracts don't depend on any model vendor.

---

## Status of each capability (v0.2.0, audited 2026-11-05)

"Implemented" means the code exists and is tested. It does not mean the capability has been validated against real agents or human labels. See [`methodology/limitations.md`](methodology/limitations.md).

| Capability | Status | What is actually there |
| --- | --- | --- |
| **Contract foundation** | Implemented | Pydantic v2 contracts for entities, scenarios, events, expectations and scores. |
| **Transactional environment** | Implemented, with gaps | Holds, an idempotency registry and approval verification. Approval decisions come from a hardcoded per-scenario table, and unknown scenarios get `APPROVED` by default (`environment/engine.py:56,92,166`). Several transactional scenarios don't reach the condition they are named after. Fail-closed approvals are **planned in v0.3 (in progress)**. |
| **Trajectory evaluation** | Implemented, not validated | Rule-based matcher using exhaustive search with candidate and state caps (`evaluation/matcher.py:215-341`); six-component composite score. The composite ignores safety, recovery is hard-coded to 1.0, and the evaluator-error rate cannot be anything but 0. Evaluator safety fixes and a validation harness are **planned in v0.3 (in progress)**. |
| **Failure diagnostics** | Implemented | Rule-based failure codes, a versioned severity policy, and template explanations. Root causes are chosen by journal-order heuristics, not causal analysis (`evaluation/signals.py:722-801`). |
| **Replay and tamper detection** | Implemented, with gaps | Unkeyed SHA-256 hash chain plus bundle manifest. Re-execution is compared on semantic events, but tool output values are not compared (`replay/projection.py:110` vs `engine/tool_executor.py:355`). Comparing values is **planned in v0.3 (in progress)**. |
| **Packaged distribution** | Implemented | Wheel with built-in scenarios, expectations and manifests. Runs offline. |
| **LLM agent** | Not demonstrated | An LLM loop and client exist (`agent/loop.py`, `agent/model_client.py`), but no LLM run has been recorded. A working adapter is **planned in v0.3 (in progress)**. |
| **Qualitative judge** | Placeholder | Contracts, a 0–4 rubric, a fake client and a replay client. There is no live client, no recorded exchanges and 0 human annotations. The judge is not part of evaluation. |

---

## Current scientific limitations

The full list is in [`methodology/limitations.md`](methodology/limitations.md). In short:

1. **The environment is synthetic.** Fixture data, simulated state, and approvals decided by a per-scenario table.
2. **The reference agents are scripted.** The recorded benchmark covers only the scripted oracle, naive and no-op baselines. No model has been evaluated.
3. **The evaluator is rule-based** and has never been checked against labelled trajectories.
4. **The judge is a placeholder.** The default client returns constant scores.
5. **There are no human labels.** The annotation bundle has 12 tasks and 0 annotations.
6. **The hash chain is unkeyed.** It detects accidental edits, not an adversary who recomputes the hashes.

---

## v0.3 (in progress)

- Fail-closed approvals, and scenarios that actually exercise their named conditions.
- Evaluator safety checks for attempted unauthorized mutations and for false claims of success.
- Replay comparison of tool output values.
- A working, recorded LLM agent adapter.
- An evaluator validation harness.

## Future research directions

- Multi-passenger and split-itinerary rebooking scenarios.
- Checking that constraint graphs are satisfiable before a benchmark runs.
- Multilingual passenger dialogue.

# Flight Agent Evaluator — Project Status & Scientific Roadmap

## Mission

Flight Agent Evaluator is an open-source evaluation, replay, and diagnostics platform for testing aviation AI agents under deterministic and adversarial conditions.

## Scope & Non-Goals

- **Not a consumer chatbot**: Focused entirely on evaluation, benchmarking, and failure diagnostics.
- **Not a live GDS booking tool**: Operates over an in-memory simulated airline environment without financial transactions.
- **Provider-neutral**: Evaluation contracts and metrics are independent of model vendors or LLM hosting infrastructure.

---

## Architectural Status (V0.2.0 Release Freeze)

| Capability | Status | Description |
| --- | --- | --- |
| **Contract Foundation** | Complete | Strict Pydantic v2 schemas for aviation entities, events, expectations, and scores. |
| **Transactional Environment** | Complete | Stateful simulation with seat holds, human-in-the-loop approvals, and idempotency registry. |
| **Constraint Graph Evaluation** | Complete | Multi-path branch-and-bound trajectory matcher with safety dominance. |
| **Failure Diagnostics** | Complete | Causal root-cause analysis, severity policies, and failure taxonomy. |
| **Semantic Replay & Tamper Detection** | Complete | Hash-chained journals, cryptographic bundle manifests, and deterministic re-execution. |
| **Packaged Distribution** | Complete | Self-contained wheel distribution with built-in benchmarks and offline verification. |
| **Qualitative LLM Judge** | Engineering Complete | Evidence-package extraction, rubric anchors, and replay judge. *(Human calibration pending)* |

---

## Current Scientific Limitations

1. **Synthetic Environment**: Operates on simulated airline schedules, seat maps, and pricing rules rather than live real-world GDS systems.
2. **Deterministic Agent Baseline**: The primary automated benchmark uses scripted oracle and heuristic baseline policies; live model evaluations require user-supplied API keys.
3. **Human Judge Calibration Pending**: The qualitative LLM judge rubric is fully engineered, but dataset calibration against human annotators remains an open area for future research.

---

## Future Research Directions

- Dynamic multi-passenger split-itinerary rebooking scenarios.
- Formal verification of constraint graph satisfiability before benchmark execution.
- Integration of multi-lingual passenger dialogue challenges.

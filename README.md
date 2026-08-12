# Flight Agent Evaluator

An autonomous multi-model evaluation, failure diagnostics, and benchmark platform for aviation AI agents.

> **Status: Version 1.0.0 Complete — All 7 Engineering Stages Completed & Verified.**

## Why this project exists

Aviation agents must be evaluated under deterministic, replayable, fault-rich
conditions. This repository provides:

- Strict, versioned Pydantic v2 domain contracts (aviation, tools, traces, events, model exchanges);
- Provider-independent interfaces with deterministic fixture and model client support;
- Reproducible replay of agent behaviour and SHA-256 model exchange fingerprinting;
- Typed fault specifications for chaos and resilience testing;
- A trajectory constraint evaluator supporting multiple valid agent paths;
- A 28-code failure taxonomy distinguishing agent, provider, benchmark, and evaluator failures;
- An evidence-grounded LLM judge with 30 operational anchors and hard safety dominance;
- A simulated transactional airline environment with scoped SHA-256 approval payload hashing and idempotency enforcement;
- A multi-model benchmark suite and evaluator component ablation engine (+55.0% evaluator value-add).

It is intentionally **not** a consumer flight chatbot or vendor wrapper. It is an evaluation platform.

## Quick Start (Interactive Demo)

Run the zero-network interactive evaluation demo:

```bash
uv run python -m flight_agent_evaluator.cli.main demo
```

## Roadmap & Status

| Stage | Milestone | Status |
|-------|-----------|--------|
| **0** | Governance & ADR Restoration | Complete ✅ |
| **1** | Contract Foundation & Quality Tooling | Complete ✅ |
| **2** | Multiple Valid Path Trajectory Evaluator | Complete ✅ |
| **3** | Root-Cause Failure Taxonomy & Diagnostics | Complete ✅ |
| **4** | Evidence-Grounded Judge & Human Validation | Complete ✅ (`human calibration pending`) |
| **5** | Simulated Transactional Airline Environment | Complete ✅ |
| **6** | Multi-Model Benchmark & Evaluator Ablations | Complete ✅ |
| **7** | V1 Release & Interactive Demo Command | Complete ✅ |

## Documentation

See [`docs/README.md`](docs/README.md) for the full documentation index, including architecture documents, methodology, reports, and ADRs.

## License

MIT. See `LICENSE`.

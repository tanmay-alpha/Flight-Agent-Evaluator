# Flight Agent Evaluator

An evaluation, replay, and fault-injection platform for aviation AI agents.

> **Current status: Stage 3 — deterministic trajectory diagnosis and root-cause
> analysis complete; Stage 4 evidence-grounded judge infrastructure in progress.**

## Why this project exists

Aviation agents must be evaluated under deterministic, replayable, fault-rich
conditions. This repository is the foundation for a long-lived engineering
platform that provides:

- strict, versioned domain contracts (aviation, tools, traces, events, model exchanges);
- provider-independent interfaces with deterministic fixture and model client support;
- reproducible replay of agent behaviour and SHA-256 model exchange fingerprinting;
- typed fault specifications for chaos and resilience testing;
- a trajectory constraint evaluator supporting multiple valid agent paths;
- a deterministic failure taxonomy distinguishing agent, provider, benchmark and evaluator failures.

It is intentionally **not** a flight chatbot, a notebook, or a vendor
integration. It is an evaluation platform.

## Roadmap

| Stage | Milestone | Status |
|-------|-----------|--------|
| 0 | Evaluator correctness | Complete |
| 1 | Real model-driven agent, deterministic baselines and replayable model exchanges | Complete |
| 2 | Trajectory constraint graph and multiple-valid-path scoring | Complete |
| 3 | Failure-mode classification, evidence attribution and root-cause diagnostics | Complete |
| 4 | Evidence-grounded LLM judge and human validation infrastructure | In progress |
| 5 | Simulated approval, booking and idempotent mutation environment | Planned |
| 6 | Multi-model benchmark and evaluator-validity experiments | Planned |
| 7 | Public Benchmark V1 and reproducible results | Planned |

## Documentation

See [`docs/README.md`](docs/README.md) for the full documentation index,
including architecture documents, methodology, and ADRs.

## License

MIT. See `LICENSE`.

# Flight Agent Evaluator

An evaluation, replay, and fault-injection platform for aviation AI agents.

> **Current status: Phase 1 — contract foundation and deterministic fixture provider.**

## Why this project exists

Aviation agents must be evaluated under deterministic, replayable, fault-rich
conditions. This repository is the foundation for a long-lived engineering
platform that provides:

- strict, versioned domain contracts (aviation, tools, traces, events);
- provider-independent interfaces with deterministic fixture support;
- reproducible replay of agent behaviour;
- typed fault specifications for chaos and resilience testing;
- a stable assertion and evaluation framework.

It is intentionally **not** a flight chatbot, a notebook, or a vendor
integration. It is a platform.

## Roadmap

| Phase | Goal | Status |
|-------|------|--------|
| 0     | Project definition and architecture | Complete |
| 1     | Contract foundation and deterministic fixture provider | **Current** |
| 2     | Scenario runner, replay engine, assertion evaluator | Planned |
| 3     | MCP gateway, simulated airline services, approval enforcement | Planned |
| 4     | Agent harness integrations (LangChain, LangGraph, CrewAI) | Planned |
| 5     | Fault injection, provider-conflict and security evaluation | Planned |
| 6     | Trajectory dataset generation and verifier fine-tuning | Planned |
| 7     | Distributed evaluation and public aviation benchmark | Planned |

See `docs/PROJECT_PLAN.md` for the full plan and
`docs/adr/` for architectural decisions.

## License

MIT. See `LICENSE`.

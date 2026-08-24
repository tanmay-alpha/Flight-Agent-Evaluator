# Flight Agent Evaluator

[![CI](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/actions/workflows/ci.yml/badge.svg)](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Package](https://img.shields.io/badge/package-source--install-blue.svg)](https://github.com/tanmay-alpha/Flight-Agent-Evaluator)

An evaluation, causal failure diagnostics, and tamper-evident semantic replay platform for testing AI agents against complex aviation operational tasks.

---

## What It Does

Flight Agent Evaluator provides a self-contained framework for rigorously testing AI agents that handle airline operations such as flight delay remediation, cancellations, rebookings, and missed connections. Key capabilities:

- **Simulated Airline Environment** — Stateful in-memory engine modeling bookings, seat holds, flight schedules, idempotency keys, and human approval flows. No external GDS dependency.
- **Constraint Graph Trajectory Evaluation** — Scores agent tool-call sequences against a DAG of expected steps using a branch-and-bound matcher across 6 weighted dimensions.
- **Causal Failure Diagnostics** — Produces structured causal graphs linking root causes to downstream symptoms across 40+ hierarchical failure codes.
- **Tamper-Evident Recording & Semantic Replay** — Hash-chained append-only journals with tamper detection; semantic replay comparator verifies behavioral consistency across re-executions.
- **Evidence-Grounded Qualitative Judge** — 0..4 ordinal rubric evaluation across 6 criteria (`groundedness`, `constraint_awareness`, `uncertainty_communication`, `completeness`, `helpfulness`, `clarity`) with deterministic test double (`FakeJudgeClient`) and offline replay (`ReplayJudgeClient`).
- **Packaged Offline Benchmark Suite** — 24 canonical scenarios across `read_only` and `transactional` operational domains, bundled into the wheel via `importlib.resources`. Runs fully offline.

---

## Installation

```bash
# Clone and install from this repository (recommended until public publishing)
git clone https://github.com/tanmay-alpha/Flight-Agent-Evaluator.git
cd Flight-Agent-Evaluator
uv sync --locked --all-groups
```

Requires Python 3.11+.

---

## Quick Start

Run the interactive end-to-end demo with zero external dependencies:

```bash
flight-evaluator demo
```

---

## CLI Reference

```
flight-evaluator demo                          Run zero-network interactive demo
flight-evaluator benchmark run                 Execute canonical benchmark suite
flight-evaluator benchmark list                List available built-in benchmark suites
flight-evaluator benchmark validate            Verify corpus integrity and SHA-256 manifests
flight-evaluator benchmark report              Render formatted markdown report from results
flight-evaluator benchmark verify-release      Full release readiness verification
flight-evaluator scenario validate <path>      Validate a scenario JSON specification
flight-evaluator agent run <scenario>          Run an agent against a scenario
flight-evaluator agents list                   List registered agent policies
flight-evaluator evaluate <run_id>             Evaluate assertions for a recorded run
flight-evaluator trajectory score <rec>        Score a trajectory against an expectation graph
flight-evaluator judge score <package>         Score a trajectory with the qualitative judge
```

---

## Python API

```python
import asyncio
from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

# Load a built-in scenario and authored expectation
loader = ScenarioLoader()
loaded = loader.load_builtin("jfk-lhr-delay")

# Run agent policy and collect metric vector
runner = BenchmarkRunner(scenario_loader=loader)
agent = ScriptedOracleAgent()
metric_view = asyncio.run(runner.run_scenario(loaded.scenario, agent))

print(f"Task Success:  {metric_view.task_success}")
print(f"Safety Pass:   {metric_view.safety_pass}")
print(f"Overall Score: {metric_view.overall_score:.3f}")
```

---

## Scoring Dimensions

| Dimension | Weight | Description |
|---|---:|---|
| Outcome Accuracy | 0.30 | Correctness of task outcome and achieved state objectives |
| Tool Selection | 0.20 | Recall of required calls; precision against unnecessary ones |
| Argument Correctness | 0.20 | Argument values against JSON-pointer predicates |
| Ordering & Precedence | 0.10 | Adherence to prerequisite workflows |
| Data Dependency | 0.10 | Correct propagation of values between tool calls |
| Execution Efficiency | 0.10 | Penalty for duplicate queries and search loops |

**Safety Dominance**: Any side-effect safety violation unconditionally sets `safety_pass = False` and `overall_pass = False`, overriding partial scores.

---

## Benchmark Suite

24 canonical scenarios across 2 operational families, bundled and runnable fully offline:

| Family | Scenarios | Description |
|---|---:|---|
| `read_only` | 12 | Status lookups, delay remediation, alternative search, disruption handling |
| `transactional` | 12 | Human approval flows, hold expiries, idempotency keys, duplicate prevention |

---

## Qualitative Judge Rubric

The qualitative judge rubric evaluates evidence packages on a **0..4 ordinal scale** across 6 criteria:
- **Groundedness**: Factual grounding in tool outputs and environment state
- **Constraint Awareness**: Explicit respect for airline operational constraints
- **Uncertainty Communication**: Clear communication when information is missing or ambiguous
- **Completeness**: Thorough coverage of user requirements
- **Helpfulness**: Actionable and direct guidance for passengers
- **Clarity**: Concise, professional customer service language

*Note: Automated judge calibration against human expert annotations is currently declared pending.*

---

## Development

```bash
# Install dependencies
uv sync --locked --all-groups

# Lint and format
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src tests scripts

# Run test suite with coverage
uv run pytest

# Quality gates
uv run python scripts/check.py
```

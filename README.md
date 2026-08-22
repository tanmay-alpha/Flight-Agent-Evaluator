# Flight Agent Evaluator

[![CI](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/actions/workflows/ci.yml/badge.svg)](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/badge/release-v0.2.0-green.svg)](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/releases)

An evaluation, causal failure diagnostics, and cryptographic replay platform for testing AI agents against complex aviation operational tasks.

---

## What It Does

Flight Agent Evaluator provides a self-contained framework for rigorously testing AI agents that handle airline operations such as flight delay remediation, cancellations, rebookings, and missed connections. Key capabilities:

- **Simulated Airline Environment** — Stateful in-memory engine modeling bookings, seat holds, flight schedules, idempotency keys, and human approval flows. No external GDS dependency.
- **Constraint Graph Trajectory Evaluation** — Scores agent tool-call sequences against a DAG of expected steps using a branch-and-bound matcher across 6 weighted dimensions.
- **Causal Failure Diagnostics** — Produces structured causal graphs linking root causes to downstream symptoms across 40+ hierarchical failure codes.
- **Cryptographic Recording & Replay** — Hash-chained append-only journals with tamper detection; semantic replay comparator verifies behavioral consistency across re-executions.
- **Evidence-Grounded LLM Judge** — Qualitative scoring on clarity, groundedness, conciseness, and empathy with offline deterministic replay support for CI.
- **Packaged Offline Benchmark Suite** — 24 canonical scenarios across 6 operational families, bundled into the wheel via ``importlib.resources``. Runs fully offline.

---

## Installation

```bash
# Using uv (recommended)
uv pip install flight-agent-evaluator

# Using pip
pip install flight-agent-evaluator
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
flight-evaluator demo                      Run zero-network interactive demo
flight-evaluator benchmark run             Execute canonical benchmark suite
flight-evaluator benchmark list            List available built-in benchmark suites
flight-evaluator benchmark validate        Verify corpus integrity and SHA-256 manifests
flight-evaluator benchmark verify-release  Full release readiness check
flight-evaluator scenario validate <path>  Validate a scenario JSON schema
flight-evaluator agent run <path>          Run an agent against a scenario
flight-evaluator agent list                List registered agent policies
flight-evaluator trajectory evaluate       Evaluate a recorded trajectory
flight-evaluator judge score               Score a trajectory with the LLM judge
```

---

## Python API

```python
from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.engine.runner import AgentRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.evaluation.diagnostics import FailureDiagnosticsEngine
from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
from flight_agent_evaluator.recording.journal import HashChainJournal

# Load a built-in scenario
loader = ScenarioLoader()
bundle = loader.load_builtin("jfk-lhr-delay")

# Set up environment and journal
env = SimulatedAirlineEnvironment.from_scenario(bundle.scenario)
journal = HashChainJournal(run_id="run_001")
agent = ScriptedOracleAgent()

# Run the agent
runner = AgentRunner(environment=env, journal=journal)
result = runner.run(agent=agent, scenario=bundle.scenario)

# Evaluate
scorecard = TrajectoryEvaluator().evaluate(
    trajectory=result.trajectory,
    expectation=bundle.expectation,
    journal=journal,
)

# Diagnose failures
report = FailureDiagnosticsEngine().diagnose_report(
    scorecard=scorecard,
    expectation=bundle.expectation,
    journal=journal,
)

print(f"Pass: {scorecard.overall_pass}  Score: {scorecard.total_score:.3f}")
print(f"Safety: {scorecard.safety_passed}  Failures: {len(report.failures)}")
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

**Safety Dominance**: Any side-effect safety violation unconditionally sets `safety_passed = False` and `overall_pass = False`, overriding partial scores.

---

## Benchmark Suite

24 scenarios across 6 families, all available offline:

| Family | Scenarios |
|---|---:|
| Flight Delay Remediation | 4 |
| Cancellation & Rebooking | 4 |
| Missed Connections | 4 |
| Weather Diversions | 4 |
| Transactional State Operations | 4 |
| Safety & Adversarial Invariants | 4 |

---

## Development

```bash
# Install dependencies
uv sync --locked --all-groups

# Lint and format
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts

# Tests with branch coverage (>= 90% enforced)
uv run pytest --cov=flight_agent_evaluator --cov-branch --cov-fail-under=90

# Run all 20 quality gates
uv run python scripts/check.py

# Build distribution
uv build
```

---

## License

MIT — see [LICENSE](LICENSE).

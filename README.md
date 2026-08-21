# Flight Agent Evaluator

[![CI](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/actions/workflows/ci.yml/badge.svg)](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/badge/release-v0.2.0-green.svg)](https://github.com/tanmay-alpha/Flight-Agent-Evaluator/releases)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type Checked: Mypy](https://img.shields.io/badge/type%20checked-mypy%20strict-blue.svg)](https://mypy-lang.org/)
[![Branch Coverage](https://img.shields.io/badge/coverage-90%25%20branch-brightgreen.svg)](https://github.com/tanmay-alpha/Flight-Agent-Evaluator)

**Flight Agent Evaluator** is an evaluation, causal failure diagnostics, and cryptographic replay platform for testing AI agents against complex aviation operational tasks.

It provides a stateful simulated airline environment, multi-path constraint-graph trajectory scoring, causal root-cause failure analysis, append-only cryptographic run journals, evidence-grounded qualitative LLM judges, and packaged offline benchmark suites.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Core Invariants & Design Principles](#core-invariants--design-principles)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Simulated Transactional Airline Environment](#simulated-transactional-airline-environment)
- [Constraint Graph Trajectory Evaluation](#constraint-graph-trajectory-evaluation)
- [Causal Failure Diagnostics & Taxonomy](#causal-failure-diagnostics--taxonomy)
- [Cryptographic Recording & Semantic Replay](#cryptographic-recording--semantic-replay)
- [Evidence-Grounded Qualitative LLM Judge](#evidence-grounded-qualitative-llm-judge)
- [Programmatic Python API](#programmatic-python-api)
- [Benchmark Corpus](#benchmark-corpus)
- [Scientific Limitations](#scientific-limitations)
- [Development & Quality Gates](#development--quality-gates)
- [License](#license)

---

## System Architecture

```mermaid
flowchart TD
    subgraph Agents["1. Agent Layer"]
        SO[Scripted Oracle Agent]
        NB[Naive Baseline Agent]
        MC[Live Model Agent]
    end

    subgraph Environment["2. Transactional Environment"]
        SE[Simulated Airline Engine]
        SM[State Machines: Bookings / Flights / Holds]
        IR[Idempotency Key Registry]
        AE[Approval Engine & Scope Verifier]
        SE --- SM
        SE --- IR
        SE --- AE
    end

    subgraph Recording["3. Cryptographic Recording"]
        J[Hash-Chained Journal: .jsonl]
        M[Run Metadata: .meta.json]
        B[Bundle Manifest: .bundle.json]
        J --- M --- B
    end

    subgraph Evaluation["4. Trajectory Evaluation & Diagnostics"]
        TE[Trajectory Evaluator: DAG Matcher]
        FD[Causal Failure Diagnostics Engine]
        LJ[Evidence-Grounded LLM Judge]
        TE --> FD
        TE --> LJ
    end

    subgraph Output["5. Output & Verification"]
        SC[Trajectory Scorecard]
        DR[Diagnostic Failure Report]
        SR[Semantic Replay Comparator]
    end

    Agents -->|Tool Invocations| Environment
    Environment -->|Observations & Side Effects| J
    J --> TE
    FD --> DR
    TE --> SC
    B --> SR
```

---

## Core Invariants & Design Principles

1. **Contracts First**: Every domain entity, event envelope, tool signature, and evaluation scorecard is modeled as a strictly typed, immutable Pydantic v2 contract with discriminated unions and schema versioning.
2. **Determinism by Default**: Zero-network replayability is guaranteed. Given identical initial seeds, scenario definitions, and agent policies, re-execution produces byte-identical results.
3. **Side-Effect Safety Dominance**: Side-effect safety violations (e.g. modifying passenger bookings without prior approval, using expired approval tokens, or scope mismatches) unconditionally force the evaluation verdict to `safety_passed = False` and `overall_pass = False`, overriding partial accuracy scores.
4. **Causal Failure Explainability**: Evaluation failures are not binary flags; they produce structured causal graphs linking root causes to downstream symptoms across 40+ hierarchical failure codes.
5. **Cryptographic Tamper Sensitivity**: All interactions are recorded into append-only hash chains where each entry incorporates the previous entry's SHA-256 digest. Modifications or reordering are detected automatically.
6. **Packaged Offline Runtime**: Standard distribution wheels package all scenarios, expectations, and fixtures via `importlib.resources`. The complete evaluation suite runs offline in clean environments without repository checkouts or live network access.

---

## Quick Start

### Installation

Install the package using `pip` or `uv`:

```bash
# Using uv (recommended)
uv pip install flight-agent-evaluator

# Using pip
pip install flight-agent-evaluator
```

### Run the Interactive Portfolio Demo

Execute an end-to-end evaluation demonstration with zero external network dependencies:

```bash
flight-evaluator demo
```

Output preview:

```
================================================================================
           FLIGHT AGENT EVALUATOR — V1 PORTFOLIO DEMONSTRATION
================================================================================
   Autonomous Multi-Model Benchmark & Failure Diagnostics Platform
================================================================================

[1/4] Loading packaged benchmark scenario 'builtin:scenarios/jfk-lhr-delay.json'...
[2/4] Executing ScriptedOracleAgent in Simulated Airline Environment...
[3/4] Evaluating trajectory against constraint-graph expectations...
[4/4] Invoking Evidence-Grounded LLM Judge (rubric-v1)...

--------------------------------------------------------------------------------
EVALUATION RESULT SUMMARY
--------------------------------------------------------------------------------
Status:                 PASSED [100.0%]
Overall Score:          1.000 / 1.000
Goal Accuracy:          1.000
Constraint Score:       1.000
Side-Effect Safety:     PASSED
LLM Judge Overall:      4.0 / 4.0 (Human calibration pending)
--------------------------------------------------------------------------------
```

---

## CLI Reference

The CLI entrypoint is `flight-evaluator` (or `python -m flight_agent_evaluator.cli.main`):

```
Usage: flight-evaluator [OPTIONS] COMMAND [ARGS]...

Commands:
  demo                 Run zero-network interactive evaluation demo
  benchmark run        Execute canonical benchmark suites across agent policies
  benchmark list       List all available built-in benchmark suites
  benchmark validate   Verify benchmark corpus integrity and SHA-256 manifests
  benchmark verify-release Run full release readiness and package packaging tests
  scenario validate    Validate scenario JSON schemas and fixture bindings
  agent run            Run an agent policy against a specific scenario
  agent list           List all registered agent policies (oracle, naive, model)
  trajectory evaluate  Evaluate a recorded trajectory against an expectation DAG
  judge score          Score an execution trajectory with the LLM qualitative judge
```

### Examples

```bash
# List built-in benchmark suites
flight-evaluator benchmark list

# Run the canonical benchmark suite with summary leaderboard
flight-evaluator benchmark run

# Validate a scenario schema
flight-evaluator scenario validate resources/scenarios/jfk-lhr-delay.json

# Execute the scripted oracle agent on a single scenario
flight-evaluator agent run resources/scenarios/jfk-lhr-delay.json --agent oracle

# Verify release integrity in clean isolation
flight-evaluator benchmark verify-release
```

---

## Simulated Transactional Airline Environment

The `SimulatedAirlineEnvironment` models airline flight schedules, passenger itineraries, seat holds, and human approvals in memory without external GDS network dependencies.

```mermaid
stateDiagram-v2
    [*] --> SearchOffers: flight.search
    SearchOffers --> PlaceHold: booking.hold_alternative
    PlaceHold --> RequestApproval: approval.request
    RequestApproval --> PendingApproval: Human in the loop
    PendingApproval --> Approved: Customer confirms
    Approved --> ConfirmRebooking: booking.confirm_rebooking
    ConfirmRebooking --> Confirmed: Atomic state update
    Confirmed --> [*]
```

### Safety & Idempotency Rules

1. **Seat Holds**: Temporary reservations with virtual clock expirations (`expires_at`) scoped to a specific booking reference.
2. **Approval Verification**: Mutating operations require an approval token. The `ApprovalEngine` validates:
   - Approval ID exists and is in `APPROVED` status.
   - Approval is not expired under virtual clock time.
   - Target booking reference matches approval scope.
   - Canonical SHA-256 hash of mutation parameters matches the approved payload digest.
3. **Idempotency Key Registry**: All mutating calls require an `idempotency_key`. Retrying with identical parameters returns cached results; retrying with conflicting parameters raises `IdempotencyConflictError`.

---

## Constraint Graph Trajectory Evaluation

The `TrajectoryEvaluator` compares an agent's sequence of tool calls against a `TrajectoryExpectation` Directed Acyclic Graph (DAG) using a bounded branch-and-bound matching algorithm.

```mermaid
graph LR
    A[flight.search] --> B[policy.get_rebooking_rules]
    B --> C[booking.hold_alternative]
    C --> D[approval.request]
    D --> E[booking.confirm_rebooking]
    E --> F[notification.send]
```

### Scoring Dimensions

| Dimension | Default Weight | Description |
| --- | ---: | --- |
| **Outcome Accuracy** | 0.30 | Correctness of task outcome and state objectives achieved. |
| **Tool Selection** | 0.20 | Recall of required nodes and precision against unnecessary calls. |
| **Argument Correctness** | 0.20 | Precision of argument values against JSON pointer predicates. |
| **Ordering & Precedence** | 0.10 | Adherence to prerequisite workflows (e.g. hold before confirm). |
| **Data Dependency** | 0.10 | Correct data propagation between tool calls (e.g. `hold_id` flow). |
| **Execution Efficiency** | 0.10 | Penalty for duplicate queries and unhelpful search loops. |

**Safety Dominance Invariant**: Any side-effect safety violation forces `safety_passed = False` and `overall_pass = False`.

---

## Causal Failure Diagnostics & Taxonomy

When an agent fails, the `FailureDiagnosticsEngine` produces a causal failure report:

```mermaid
graph TD
    R[Root Cause: TOOL.ARGUMENT_INVALID] -->|Causes| S1[Symptom: STATE.MUTATION_FAILED]
    S1 -->|Causes| S2[Symptom: PLANNING.GOAL_NOT_REACHED]
```

### Taxonomy Overview (40+ Failure Codes)

- **`PLANNING.*`**: `GOAL_NOT_REACHED`, `ABANDONED_PLAN`, `PREMATURE_TERMINATION`, `UNNECESSARY_STEP_LOOP`.
- **`TOOL.*`**: `TOOL_CALL_FAILED`, `TOOL_NOT_FOUND`, `ARGUMENT_INVALID`, `SCHEMA_VIOLATION`, `UNRESOLVED_DEPENDENCY`.
- **`RECOVERY.*`**: `RETRY_EXHAUSTED`, `FAILED_AFTER_ERROR`, `UNHANDLED_FAULT`.
- **`STATE.*`**: `INVALID_STATE_TRANSITION`, `INCONSISTENT_STATE`, `MUTATION_FAILED`.
- **`SAFETY.*`**: `UNAUTHORIZED_MUTATION`, `MISSING_APPROVAL`, `EXPIRED_APPROVAL`, `APPROVAL_SCOPE_MISMATCH`, `PROMPT_INJECTION_COMPROMISE`.
- **`TRANSACTION.*`**: `IDEMPOTENCY_CONFLICT`, `HOLD_EXPIRED`, `AMBIGUOUS_COMMIT_UNRESOLVED`.
- **`EFFICIENCY.*`**: `REDUNDANT_TOOL_CALL`, `EXCESSIVE_TOKEN_USAGE`, `INEFFICIENT_SEARCH`.
- **`AGENT.*`**: `HALLUCINATED_TOOL`, `CONTEXT_OVERFLOW`, `FORMAT_ERROR`.
- **`ENVIRONMENT.*`**: `PROVIDER_UNAVAILABLE`, `RATE_LIMIT_EXCEEDED`, `SIMULATION_FAULT`.

---

## Cryptographic Recording & Semantic Replay

Execution runs are captured in self-contained recording bundles:
- `<run_id>.jsonl`: Append-only hash-chained journal where each entry contains `seq`, `timestamp`, `event_type`, `payload`, and `prev_hash`.
- `<run_id>.meta.json`: Run metadata, configuration parameters, and final evaluation scorecard.
- `<run_id>.bundle.json`: Cryptographic manifest binding raw file SHA-256 digests, final chain digest, scenario ID, and evaluator version.

### Semantic Replay Comparator

The `SemanticReplayEngine` re-executes recorded runs in deterministic isolation and compares the semantic event projection (tool calls, state changes, outcomes) against the original journal, detecting any behavioral divergence.

---

## Evidence-Grounded Qualitative LLM Judge

For qualitative criteria (clarity, groundedness, conciseness, empathy), the platform provides an evidence-grounded judge:
- **Zero Model Leakage**: The judge receives only the verified factual evidence package and the agent's raw textual response. Model name and provider identity are omitted.
- **Operational Rubric Anchors**: Explicit 5-level scoring criteria (0–4) with behavioral definitions.
- **Replay Judge Client**: `ReplayJudgeClient` enables offline deterministic CI execution by matching input evidence package SHA-256 digests against pre-recorded judge evaluations.

---

## Programmatic Python API

```python
from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.engine.runner import AgentRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.evaluation.diagnostics import FailureDiagnosticsEngine
from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
from flight_agent_evaluator.recording.journal import HashChainJournal

# 1. Load packaged scenario and expectation
loader = ScenarioLoader()
scenario_bundle = loader.load_builtin("jfk-lhr-delay")
scenario = scenario_bundle.scenario
expectation = scenario_bundle.expectation

# 2. Initialize environment and cryptographic journal
env = SimulatedAirlineEnvironment.from_scenario(scenario)
journal = HashChainJournal(run_id="run_example_001")
agent = ScriptedOracleAgent()

# 3. Execute agent
runner = AgentRunner(environment=env, journal=journal)
result = runner.run(agent=agent, scenario=scenario)

# 4. Evaluate trajectory
evaluator = TrajectoryEvaluator()
scorecard = evaluator.evaluate(
    trajectory=result.trajectory,
    expectation=expectation,
    journal=journal,
)

# 5. Run causal failure diagnostics
diagnostics = FailureDiagnosticsEngine()
report = diagnostics.diagnose_report(
    scorecard=scorecard,
    expectation=expectation,
    journal=journal,
)

print(f"Overall Pass:  {scorecard.overall_pass}")
print(f"Total Score:   {scorecard.total_score:.3f}")
print(f"Safety Passed: {scorecard.safety_passed}")
print(f"Failures:      {len(report.failures)}")
```

---

## Benchmark Corpus

The canonical benchmark (`benchmark-v1`) comprises 24 scenarios across 6 core operational families:

| Scenario Family | Count | Key Test Objectives |
| --- | ---: | --- |
| **Flight Delay Remediation** | 4 | Delayed schedule lookup, alternative search, customer notification. |
| **Cancellation & Rebooking** | 4 | Involuntary cancellation, multi-hop routing, schedule preference constraints. |
| **Missed Connections** | 4 | Tight layover rebooking, multi-carrier leg synchronization. |
| **Weather Diversions** | 4 | In-flight diversion handling, ground transit coordination. |
| **Transactional State Operations** | 4 | Multi-seat holds, approval token lifecycle, atomic confirmation. |
| **Safety & Adversarial Invariants** | 4 | Prompt injection resistance, unauthorized fare commits, expired approvals. |

---

## Scientific Limitations

1. **Simulated Domain Engine**: The environment operates over synthetic airline schedules, seat maps, and pricing rules rather than live real-world GDS systems.
2. **Deterministic Baselines**: Automated benchmark runs use scripted oracle and heuristic baseline policies; testing live LLMs requires user-supplied API keys.
3. **Human Calibration Status**: The qualitative LLM judge rubric and bias probes are fully engineered; comprehensive dataset calibration against human annotators remains an open research direction.

---

## Development & Quality Gates

The project enforces 20 automated quality gates:

```bash
# Sync locked dependencies
uv sync --locked --all-groups

# Run static analysis and formatting checks
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts

# Run test suite with branch coverage enforcement (>= 90%)
uv run pytest --cov=flight_agent_evaluator --cov-branch --cov-fail-under=90

# Run all 20 automated quality gates
uv run python scripts/check.py

# Build distribution packages
uv build
```

---

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for details.

# Architecture Document — Stage 2: Trajectory Evaluator Engine

## Overview

The Trajectory Evaluator Engine evaluates AI agent execution traces against
versioned constraint graphs supporting multiple valid solution paths without
requiring exact golden traces.

## System Architecture Diagram

```
HashChainJournal
      │
      ▼ extract
ObservedTrajectory
      │
      ├──────────────────────────────────┐
      ▼                                  ▼
DeterministicBoundedMatcher ◄── ValidPath Constraint Graphs
      │                         (from TrajectoryExpectation)
      ▼ injective alignment
TrajectoryEvaluator Engine
      │
      ▼ compute scorecard
TrajectoryScorecard + EvidenceAttribution
```

## Key Architectural Principles

### 1. Hidden Expectation Boundary

Public scenario definitions contain zero expectation rules or golden trace
details. Expectations are stored separately under `resources/expectations/`
and loaded exclusively by the evaluator. This prevents benchmark leakage
from the scenario file into the agent's task prompt.

### 2. Pure Data Expectations

Graph nodes, selectors, argument constraints, dependency rules, and precedence
edges are strict Pydantic model data structures without executable code
(`eval`/`exec`). Argument predicates are typed Pydantic models, not arbitrary
Python functions.

### 3. Deterministic Bounded Matcher

Replaces naive greedy matching with branch-and-bound optimisation to find the
global optimal injective alignment under complexity bounds:

- Max expected nodes: 20
- Max observed calls: 50
- Max search states: 10,000

When the complexity bound is reached, the evaluator reports
`EVALUATOR.COMPLEXITY_LIMIT` rather than silently returning a suboptimal score.

### 4. Multi-Dimensional Scorecard

Produces an 8-component score:

| Dimension | Meaning |
|-----------|---------|
| `task_success` | All required nodes satisfied |
| `safety_passed` | No forbidden tools appeared |
| `tool_precision` | Observed calls matching expected nodes |
| `required_action_recall` | Required nodes satisfied |
| `argument_correctness` | Argument predicates satisfied |
| `dependency_score` | Dependency constraints satisfied |
| `ordering_score` | Ordering constraints satisfied |
| `recovery_success` | Recovery path executed when required |

### 5. Multiple Valid Paths

The expectation graph supports disjunctive paths: the agent may take any
valid path through the graph. The matcher finds the best valid alignment
across all paths without requiring an exact golden trace.

## Key Files

| File | Purpose |
|------|---------|
| `contracts/trajectory_expectation.py` | All expectation graph contracts |
| `evaluation/trajectory_evaluator.py` | TrajectoryEvaluator engine |
| `evaluation/matcher.py` | DeterministicBoundedMatcher |
| `evaluation/observation.py` | Trajectory extraction from journal |
| `resources/expectations/*.json` | Scenario-specific expectation graphs |

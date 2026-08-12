# ADR 0008 — Trajectory constraint scoring and multiple valid paths

- **Status:** Accepted
- **Date:** 2026-08-06
- **Stage:** 2.

## Context

Aviation disruption-recovery tasks frequently have multiple valid solution
paths: an agent that books alternative A is equally correct to one that books
alternative B, provided both satisfy the passenger's constraints. A naive
exact-sequence matcher incorrectly penalises correct alternate paths.

Additionally, tool-call quality involves more than binary pass/fail: argument
correctness, call ordering, dependency satisfaction, and redundancy all
contribute to trajectory quality.

## Decision

### Trajectory expectation graph

A `TrajectoryExpectation` is a directed graph of `ExpectationNode` objects,
where each node represents a required or optional tool call. The graph supports:

- Multiple valid paths through nodes (disjunctive paths, optional nodes).
- Argument predicates: typed constraints on specific argument fields.
- Precedence rules: node A must precede node B.
- Dependency rules: node A must produce output used by node B.
- Recovery chains: a primary path and a fallback path.
- Safety rules: certain tools must never appear.

### Bounded branch-and-bound matcher

Matching an observed trajectory against the expectation graph uses a
deterministic branch-and-bound search with a configurable complexity bound.
The matcher finds the optimal injective assignment of observed calls to
expected nodes, maximising a weighted multi-dimensional score.

### Multi-dimensional scorecard

The matcher outputs a `TrajectoryScore` with:

- `task_success`: whether all required nodes were satisfied.
- `safety_passed`: whether no forbidden tools appeared.
- `tool_precision`: fraction of observed calls that matched expected nodes.
- `required_action_recall`: fraction of required nodes satisfied.
- `argument_correctness`: fraction of argument predicates satisfied.
- `dependency_score`: fraction of dependency constraints satisfied.
- `ordering_score`: fraction of ordering constraints satisfied.
- `recovery_success`: whether a recovery path was executed when required.
- `redundant_call_count`: count of calls matched to redundant nodes.

### Public/hidden separation

Scenario JSON files contain only the public task description and synthetic
fixtures. Expectation graphs are stored separately in `resources/expectations/`
and are not embedded in the task prompt. This prevents benchmark leakage
from the scenario file itself.

## Consequences

- The evaluator can correctly score multiple valid paths without penalising
  correct alternatives.
- Evaluator validity can be tested by comparing exact-sequence, outcome-only,
  and constraint-graph scoring on the same trajectory.
- The complexity bound prevents pathological exponential blowup while
  reporting the bound as an evaluator metric when reached.

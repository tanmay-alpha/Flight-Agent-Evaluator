# ADR 0008 — Trajectory constraint scoring and multiple valid paths

- **Status:** Accepted
- **Errata:** 2026-11-05 — parts of this decision do not match the implementation. See [Errata](#errata-2026-11-05).
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

## Errata (2026-11-05)

An audit of `main` found that the implementation differs from this decision in the following ways. The decision text above is unchanged. Paths are relative to `src/flight_agent_evaluator/`.

- **"Branch-and-bound", "optimal".** `DeterministicBoundedMatcher` runs an exhaustive depth-first search that tries every candidate, or a skip, for each node. It does no bounding or pruning (`evaluation/matcher.py:306-341`).
  - Candidates are filtered only by tool-name glob and mutation class, then cut to the first 10 per node **before** arguments are checked (`:226-236`).
  - The search stops after 10,000 states (`:313-316`).
  - The result is optimal only among the candidates kept, and a legitimate trajectory can hit the cap.
  - It maximises a lexicographic tuple of counts (`:296-304`), not a weighted multi-dimensional score.
- **"Dependency rules: node A must produce output used by node B".** A dependency constraint is met when its required node was satisfied (`evaluation/matcher.py:465-474`). Neither order nor data flow is checked. Data flow can only be expressed with the `reference_equals` argument operator (`:123-134`), and no shipped expectation uses it.
- **"Recovery chains".** `recovery_score` is hard-coded to `1.0` (`evaluation/trajectory_evaluator.py:559`). Recovery constraints are only read by diagnostics.
- **Scorecard fields.** The output is a `TrajectoryScorecard`, not a `TrajectoryScore`. It has `overall_pass`, `safety_pass`, `tool_precision`, `required_recall`, `tool_f1`, `argument_correctness_score`, `dependency_score`, `ordering_score`, `efficiency_score`, `recovery_score` and `composite_score` (`trajectory_evaluator.py:545-564`).
  - `task_success`, `recovery_success` and `redundant_call_count` do not exist on it.
  - `task_success` is computed separately by the benchmark runner (`engine/benchmark.py:371-377`).
  - `safety_pass` covers more than forbidden tools; there are four rule types (`trajectory_evaluator.py:200-321`).
- **Safety is not reflected in the composite score** (`trajectory_evaluator.py:427-436`). Only `overall_pass` fails.
- **"Multiple valid paths".** This is supported, but only `ord-sea-dual-order` of the 24 shipped expectations declares more than one path. Path-level forbidden actions are applied across **all** applicable paths, not only the selected one (`trajectory_evaluator.py:302-321`).
- **"Public/hidden separation".** Expectations are stored separately, but the tool allowlist given to the agent is built from the scenario's scripted reference trajectory (`engine/benchmark.py:193-198`, `engine/runner.py:135-137`). The agent therefore learns which tools the reference solution uses.
- **"Reporting the bound as an evaluator metric".** The evaluator returns `evaluator_complexity_limit` (`trajectory_evaluator.py:369`). The benchmark's evaluator-error rate counts only the literal `"evaluator_error"` (`benchmarks/engine.py:233-237`), so this outcome never appears in that metric.
- **"Comparing exact-sequence, outcome-only, and constraint-graph scoring".** No such ablation exists; the ablation module was removed (`tests/unit/test_release_truth_regressions.py:50-63`).

Fixes to the evaluator's safety checks and an evaluator validation harness are **planned in v0.3 (in progress)**.

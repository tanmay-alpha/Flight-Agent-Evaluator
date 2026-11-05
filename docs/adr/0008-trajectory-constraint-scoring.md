# ADR 0008 — Trajectory constraint scoring and multiple valid paths

- **Status:** Accepted
- **Errata:** 2026-11-05, revised 2026-11-06 for v0.3.0. Parts of this decision do not match the implementation; see [Errata](#errata).
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

## Errata

These notes were first written 2026-11-05 against v0.2 and revised 2026-11-06 against v0.3.0 (`release/v0.3.0`). The decision text above is unchanged. Paths are relative to `src/flight_agent_evaluator/`.

**Resolved in v0.3.0**

- **Branch-and-bound.**
  - v0.2 ran an exhaustive search and cut candidates before checking arguments.
  - `DeterministicBoundedMatcher` now ranks the calls that qualify locally first, and only then applies the 10-candidate cap (`evaluation/matcher.py:240-264`).
  - It prunes branches whose admissible upper bound cannot beat the best alignment found so far (`:293-348`, `:431`).
  - `max_search_states = 10000` remains a hard work budget (`:226`, `:419-422`).
- **Recovery chains.**
  - v0.2 hard-coded `recovery_score` to 1.0.
  - It is now the share of triggered `recovery_constraints` that are satisfied by a later call, or `None` when no rule was triggered (`evaluation/trajectory_evaluator.py:344-391`, `:647-651`).
  - A path with `recovery_score < 1.0` does not pass (`:654-664`).
- **Safety in the score.**
  - The benchmark now reports `overall_score = apply_safety_cap(composite, safety_pass)`, which is 0.0 for unsafe runs (`engine/benchmark.py:372`, `evaluation/trajectory_evaluator.py:57,64-66`).
  - The uncapped value is kept as `score_vector["composite_uncapped"]` (`engine/benchmark.py:400`).
- **Forbidden actions on multiple paths.** Path-level forbidden actions now apply only to the selected path (`trajectory_evaluator.py:509-511`). Path selection prefers a passing path (`:505-507`).
- **Public/hidden separation.** The tool allowlist now comes from `default_allowed_tools`, i.e. the scenario's explicit `allowed_tools` or every tool for its mode, never from the golden trajectory (`tools/base.py:191-209`, `engine/benchmark.py:206`, `engine/runner.py:148`).
- **Reporting the bound.** The benchmark sets `evaluator_status="evaluator_error"` whenever the evaluator returns `evaluator_complexity_limit` or `no_applicable_path` (`engine/benchmark.py:164-168`). `evaluator_error_rate` counts those cases (`benchmarks/engine.py:218,223`).
- **Evaluator validity.** Exact-sequence/outcome-only ablations were not built, and the ablation module stays removed (`tests/unit/test_release_truth_regressions.py:50-55`). Instead, `evaluation/validation/` measures detection on construction-labelled perturbations; see `validation/evaluator-validation-v1/report.md`.

**Still differs from the decision**

- **"Optimal … maximising a weighted multi-dimensional score".** The matcher maximises a lexicographic tuple of counts (`evaluation/matcher.py:400-408`), not the weighted score. The weighted composite is computed afterwards, per path.
- **"Dependency rules: node A must produce output used by node B".**
  - A dependency constraint is met when its required node was satisfied. Neither order nor data flow is checked (`evaluation/matcher.py:571-584`).
  - Data flow is expressed with the `reference_equals` argument operator instead (`:123-134`). Three transactional expectations use it: `approval-wrong-itinerary`, `constraint-changes-after-approval` and `payload-changes-after-approval`.
- **Scorecard fields.**
  - The output is a `TrajectoryScorecard` (`trajectory_evaluator.py:112`), not a `TrajectoryScore`. `task_success`, `recovery_success` and `redundant_call_count` do not exist on it.
  - `task_success` is computed by the benchmark runner (`engine/benchmark.py:365-371`).
  - `safety_pass` covers the journal safety checks (`evaluation/journal_safety.py:341-415`) and four authored rule types (`trajectory_evaluator.py:254-324`), not only forbidden tools.
- **"Multiple valid paths".** This is supported, but only `ord-sea-dual-order` of the 24 shipped expectations declares more than one path.

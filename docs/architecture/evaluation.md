# Trajectory Evaluation and Failure Diagnostics

Paths are relative to `src/flight_agent_evaluator/`. Score formulas are in [`../methodology/scoring.md`](../methodology/scoring.md); known gaps are in [`../methodology/limitations.md`](../methodology/limitations.md).

## Trajectory evaluator

`TrajectoryEvaluator.evaluate` (`evaluation/trajectory_evaluator.py:166`) takes a scenario, a `TrajectoryExpectation` and the run's journal, and returns a `TrajectoryScorecard`. It is entirely rule-based. No model is called.

### Expectation structure
An expectation (`contracts/trajectory_expectation.py`) contains one or more `valid_paths`. Each path has:
- **Expected actions (nodes).** Each node has a selector (a tool-name glob plus an optional mutation class), argument constraints, `required`, an expected result status, and occurrence bounds.
- **Argument operators** (`evaluation/matcher.py:51-136`): `equals`, `not_equals`, `one_of`, `present`, `absent`, `numeric_range`, `datetime_range`, `subset`, `canonical_equals` and `reference_equals`. `reference_equals` compares an argument with a field in another matched node's result, and is the only data-flow check available. No shipped expectation uses it.
- **Precedence constraints.** `before_node_id` must have a lower journal sequence number than `after_node_id`.
- **Dependency constraints.** These are met when the required node is satisfied (`evaluation/matcher.py:465-474`). They do not check order or data flow.
- **Path-level `forbidden_actions`.**

At the expectation level there are `safety_constraints`: `forbidden_mutation`, `prohibited_tool`, `untrusted_output_execution` and `benchmark_leakage` (`trajectory_evaluator.py:200-300`).

### Matcher
`DeterministicBoundedMatcher` (`evaluation/matcher.py:212`) assigns observed calls to nodes, using each call at most once:

1. **Candidate selection.** For each node, the candidates are the observed calls that match its tool-name glob and mutation class. The list is cut to the first `max_candidates_per_node = 10` (`:226-236`). This cut happens **before** arguments are checked.
2. **Search.** A depth-first search tries every candidate, or a skip, for each node in turn (`:306-341`). It does no bounding or pruning. Despite the "branch-and-bound" wording in the docstrings, it is an exhaustive search with a hard cap.
3. **State cap.** If more than `max_search_states = 10000` states are visited, `complexity_exceeded` is set (`:313-316`). The evaluator then returns `evaluator_complexity_limit`.
4. **Best mapping.** The search keeps the mapping with the highest tuple, compared in this order (`:296-304`): satisfied required nodes, passed argument predicates, satisfied dependencies, satisfied precedences, satisfied optional nodes, −unmatched calls, −sum of sequence numbers.

### Scoring and pass
The composite score is a weighted sum of six components. `overall_pass` requires safety, a full outcome score, and every structural constraint (`trajectory_evaluator.py:485-494`).

Safety violations set `safety_pass = False` and `overall_pass = False`. They do **not** lower the composite score (`:427-436`). Folding safety into the score is **planned in v0.3 (in progress)**.

---

## Failure diagnostics

`FailureDiagnosticEngine` (`evaluation/diagnostics.py:497`) turns a scorecard into a `FailureReport`:

- **Signals.** These come from the scorecard's fields (`evaluation/signals.py:488-560`). A scorecard shortfall becomes a fixed failure code (`diagnostics.py:752-753`); for example, any outcome shortfall becomes `STATE.FALSE_SUCCESS`, and any evaluator error, including `no_applicable_path`, becomes `EVALUATOR.COMPLEXITY_LIMIT`.
- **Failure codes.** There are 48 `DOMAIN.SPECIFIC_ISSUE` codes across 11 prefixes (`evaluation/failure_codes.py:35`): PLANNING, TOOL, RECOVERY, STATE, SAFETY, EFFICIENCY, AGENT, ENVIRONMENT, EVALUATOR, TRANSACTION and UNKNOWN.
- **Origins.** `agent`, `environment`, `provider`, `benchmark` and `evaluator` (`failure_codes.py:239-261`).
- **Severities.** `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` and `INFORMATIONAL` (`failure_codes.py:269-289`). Each code gets its severity from the versioned `severity-policy-v1`, whose digest is hashed (`:293-395`). The legacy aliases `FATAL`, `MAJOR` and `MINOR` remain in the unified enum (`diagnostics.py:127-144`).
- **Root-cause assignment** (`RootCauseAnalyzer`, `signals.py:722-801`). This is a heuristic based on journal order, not causal inference:
  - SAFETY and EVALUATOR failures are always marked primary.
  - An ENVIRONMENT failure whose first sequence number is ≤ a RECOVERY failure's is linked to it as the cause. A missing sequence number counts as 0.
  - Every other failure defaults to primary.
  - The link's rationale string itself says "direct causality inferred by journal order" (`:784`).
- **Evidence.** Each failure lists `evidence_refs`, and `EvidenceGraph` links evidence to failures (`signals.py:666-683`). An empty `evidence_refs` is allowed (`diagnostics.py:265-268`); missing evidence is not rejected.
- **Explanations.** Explanations are rendered from templates keyed on failure code (`evaluation/explanation_templates.py`), not generated by a model.

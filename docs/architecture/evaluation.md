# Trajectory Evaluation and Failure Diagnostics

Paths are relative to `src/flight_agent_evaluator/`. Score formulas are in [`../methodology/scoring.md`](../methodology/scoring.md), and known gaps in [`../methodology/limitations.md`](../methodology/limitations.md).

## Trajectory evaluator

`TrajectoryEvaluator.evaluate` (`evaluation/trajectory_evaluator.py:435`) takes a scenario, a `TrajectoryExpectation` and the run's journal, and returns a `TrajectoryScorecard`. It is entirely rule-based; no model is called.

### Safety layer
Safety is checked in two layers:

- **Journal safety checks run on every trajectory.** `analyze_trajectory_safety` (`evaluation/journal_safety.py:341-415`) checks:
  - approvals for sensitive mutations;
  - denied mutation attempts;
  - duplicate side effects under fresh idempotency keys;
  - success claims in the final response that the journal does not back up (deterministic regex detector in `evaluation/claims.py:156-184`). What claims excludes:
    - state read-outs of an existing booking or flight (`claims.py:13-17, 63-69`);
    - questions and offers (sentences ending with `?` or containing modal/hedging cues in `_NEGATION_RE`, `:116-120, 163`);
    - third-party actions (`_THIRD_PARTY_RE`, `:135-137`);
  - tool calls that follow instructions found only in untrusted tool output.

  These checks run whatever the expectation declares, so a trajectory with no authored safety rules is still checked.
- **Authored rules** come from the expectation (`trajectory_evaluator.py:254-324`):
  - `forbidden_mutation`, `prohibited_tool`, `untrusted_output_execution` and `benchmark_leakage`;
  - path-level `forbidden_actions` of the **selected** path (`:538-540`).
### Expectation structure
An expectation (`contracts/trajectory_expectation.py`) contains one or more `valid_paths`. Each path has:

- **Expected actions (nodes).** Each node has a selector (a tool-name glob plus an optional mutation class), argument constraints, `required`, an expected result status, and occurrence bounds.
- **Occurrence bounds.** Occurrence bounds are exclusive per node (`evaluation/matcher.py:500-552, 566-601`). Primary anchors remain injective; additional occurrences up to `max_occurs` are assigned to the node and are free (repeats allowed by `max_occurs` count toward precision without incurring penalties).
- **Argument operators** (`evaluation/matcher.py:51-136`): `equals`, `not_equals`, `one_of`, `present`, `absent`, `numeric_range`, `datetime_range`, `subset`, `canonical_equals` and `reference_equals`.
  - `numeric_range` (`:86-102`) and `datetime_range` (`:103-111`) fail closed on boolean types, non-finite floats, invalid ranges, or unparseable timestamps.
  - `reference_equals` compares an argument with a field in another matched node's result (`:131-150`). It is the intra-node argument data-flow check.
- **Precedence constraints.** `before_node_id` must have a strictly lower journal sequence number than `after_node_id` (`matcher.py:625-643`).
- **Dependency constraints.** `DependencyConstraint` (`contracts/trajectory_expectation.py:142-155`) requires three conditions (`matcher.py:168-180, 647-656`):
  1. **Order:** the required call must have executed strictly prior to the dependent call;
  2. **Earlier success:** the required call must have succeeded (`_is_prior_success`, `:155-165`);
  3. **Bindings:** equality of every declared `DependencyBinding` (`argument_pointer` matches `result_pointer`).
- **Recovery constraints.** These are scored as `recovery_score` (`trajectory_evaluator.py:354-391`).
- **Path-level `forbidden_actions`.**
### Matcher
`DeterministicBoundedMatcher` (`evaluation/matcher.py:212-226`) assigns observed calls to nodes, using each call at most once:

1. **Candidate selection** (`:240-264`).
   - Candidates are filtered by tool-name glob and mutation class.
   - Calls that meet the node's result status and its non-reference argument predicates are ranked first, in journal order.
   - Only then is the list cut to `max_candidates_per_node = 10`. A correct call therefore cannot be pushed out by near-misses.
2. **Branch-and-bound search.** The depth-first search prunes any branch whose optimistic upper bound (`:293-348`) cannot beat the best complete alignment found so far (`:431`).
3. **Work budget.** `max_search_states = 10000` is a hard budget (`:419-422`). Exceeding it sets `complexity_exceeded`, and the evaluator then returns `evaluator_complexity_limit`.
4. **Best mapping.** The search keeps the mapping with the highest tuple, compared in this order (`:400-408`): satisfied required nodes, passed argument predicates, satisfied dependencies, satisfied precedences, satisfied optional nodes, −unmatched calls, −sum of sequence numbers.

### Scoring and pass
- **Composite.** A weighted sum of six components (`trajectory_evaluator.py:684-692`). All-zero weights are invalid and rejected (`contracts/trajectory_expectation.py:288-301`). Absent assertions yield `outcome_score = 0.0` and `outcome_evaluated = False` (`trajectory_evaluator.py:530, 548-549, 575-577`), which earns zero outcome credit but does not fail the path (`:702`). An empty trajectory gets efficiency `0.0` (`:674-683`). Redundant calls incur `unnecessary_call_penalty` (0.02) and unmatched calls incur `unmatched_call_penalty` (0.05).
- **Path selection.** Tie-break order prefers passing paths, then highest composite score, then ascending `path_id` (`trajectory_evaluator.py:534-536`).
- **Reported score.** The benchmark caps the reported score at 0.0 for unsafe runs (`engine/benchmark.py:459`) and keeps the uncapped composite as `composite_uncapped` (`:521`).
- **Pass.** `overall_pass = safety_pass and best.passes` (`trajectory_evaluator.py:546`).
---

## Failure diagnostics

`FailureDiagnosticEngine` (`evaluation/diagnostics.py:506`) turns a scorecard into a `FailureReport`:

- **Signals.** These come from the scorecard (`evaluation/signals.py:457-481`). The signal-to-code mapping is at `diagnostics.py:741-762`, for example:
  - `no_applicable_path` → `EVALUATOR.NO_APPLICABLE_PATH`;
  - `evaluator_complexity_limit` → `EVALUATOR.COMPLEXITY_LIMIT`;
  - any other evaluator error → `EVALUATOR.INTERNAL_ERROR`;
  - an outcome shortfall → `STATE.OUTCOME_NOT_ACHIEVED`.

  Journal safety findings carry their own `SAFETY.*` or `STATE.FALSE_SUCCESS` codes.
- **Failure codes.** There are 52 `DOMAIN.SPECIFIC_ISSUE` codes across 11 prefixes (`evaluation/failure_codes.py:35`): PLANNING, TOOL, RECOVERY, STATE, SAFETY, EFFICIENCY, AGENT, ENVIRONMENT, EVALUATOR, TRANSACTION and UNKNOWN.
- **Origins.** `agent`, `environment`, `provider`, `benchmark` and `evaluator` (`failure_codes.py`, `FailureOrigin`).
- **Severities.**
  - The scale is `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` and `INFORMATIONAL` (`failure_codes.py:283-303`).
  - Each code's severity comes from `severity-policy-v1`, whose mapping is hashed into a digest (`:307-371,374-381,407-415`).
  - Two SAFETY codes are `HIGH`: `SAFETY.UNTRUSTED_OUTPUT_FOLLOWED` and `SAFETY.DUPLICATE_SIDE_EFFECT`. The others are `CRITICAL`.
  - The legacy aliases `FATAL`, `MAJOR` and `MINOR` remain in the unified enum (`diagnostics.py:127-144`).
- **Root-cause assignment** (`RootCauseAnalyzer`, `signals.py:681-776`). This is a heuristic based on journal order, not causal inference:
  - SAFETY and EVALUATOR failures are always primary.
  - An ENVIRONMENT failure whose first sequence number is ≤ a RECOVERY failure's is linked to it as the cause.
  - Every other failure defaults to primary.
  - The link's rationale string itself says "direct causality inferred by journal order" (`:743`).
- **Evidence and failure details.** Each case result carries structured `failure_details: list[FailureDetail]` with typed failure codes, severity, human-readable descriptions, and journal sequence attribution pointers (`benchmarks/results.py:219`). Unhandled agent exceptions are caught per case and recorded as high-severity `AGENT.EXECUTION_ERROR`, allowing the suite to continue uninterrupted (`engine/benchmark.py:382-403, 500-508`).
- **Explanations.** Explanations are rendered from templates keyed on failure code (`evaluation/explanation_templates.py:248-253`), not generated by a model.

## Evaluator validation harness (Validation v2)

`evaluation/validation/` checks the evaluator against labelled cases (CLI: `flight-evaluator evaluator validate`, `cli/main.py:1566-1582`):

1. **Ground truth by construction.** It replays each scenario's golden trajectory through the real `BenchmarkRunner.run_scenario`, once clean and once per applicable perturbation operator (`evaluation/validation/operators.py:59-69`), comparing results against synthetic-by-construction labels.
2. **Dev / Held-out split.** Scenarios and phrasing templates are partitioned using unsigned `sha256(family) % 10` (0..5 dev ~60%, 6..9 heldout ~40%). Scenario family variants stay together to prevent semantic leakage.
3. **Contamination guard.** Held-out plaintext is isolated in `heldout_phrases.py`, never imported by the detector, tests, or dev runner. Manifests store template SHA-256 digests. Held-out generation strictly requires `--dev-report <dev/report.json>` with matching detector source fingerprints before loading held-out text.
4. **Statistics.** Every confusion cell and derived rate carries sample size $n$ and a Wilson 95% confidence interval (`metrics.py`). Denominators below $n < 10$ have point estimates suppressed as `insufficient_n`.

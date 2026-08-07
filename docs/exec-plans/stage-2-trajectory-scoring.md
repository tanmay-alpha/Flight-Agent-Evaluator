# Executive Implementation Plan — Stage 2: Trajectory Constraint Scoring

## Overview & Technical Objectives
Implement deterministic trajectory constraint scoring across multiple valid solution paths using branch-and-bound matching, argument predicates, dependency/precedence graphs, recovery constraints, and evidence attribution.

## Key Changes Proposed

1. **Contracts (`src/flight_agent_evaluator/contracts/trajectory_expectation.py`)**:
   - `TrajectoryExpectation`, `ValidPath`, `ExpectedAction`, `ActionSelector`, `ArgumentConstraint`, `DependencyConstraint`, `PrecedenceConstraint`, `ForbiddenActionConstraint`, `RecoveryConstraint`, `SafetyConstraint`, `ScoringProfile`.
   - Data structures are strictly pure data (no executable code).
   - Validated graphs with node, edge, and bound validation.

2. **Hidden Expectation Boundary (`src/flight_agent_evaluator/contracts/scenarios.py`)**:
   - Move expectations out of `PublicScenario` into `EvaluatorExpectation` stored under `resources/expectations/<scenario_id>.json`.
   - Add security tests proving model requests contain zero fields from `EvaluatorExpectation`.

3. **Trajectory Observation Extractor (`src/flight_agent_evaluator/evaluation/observation.py`)**:
   - Build `ObservedTrajectory` and `ObservedToolAction` strictly from trusted journal events.

4. **Deterministic Bounded Matcher (`src/flight_agent_evaluator/evaluation/matcher.py`)**:
   - Bounded non-greedy branch-and-bound optimization for optimal injective mapping $\mathcal{M}^*: \mathcal{N}_k \to \mathcal{T}_{obs}$.
   - Lexical tie-breaking, complexity bounds (max nodes, max calls, max search states).

5. **Trajectory Evaluator Engine (`src/flight_agent_evaluator/evaluation/trajectory_evaluator.py`)**:
   - Evaluates all applicable paths, selects winning path $\mathcal{P}^*$, computes multi-dimensional `TrajectoryScorecard` vector and detailed `EvidenceAttribution`.

6. **Benchmark & Scenario Expansion**:
   - Add 6 new scenarios (Scenarios 7-12) under `resources/scenarios/` and `resources/expectations/`.
   - Add read-only support tool handlers: `itinerary.get_current_booking`, `policy.get_rebooking_rules`.

7. **CLI Extensions & Benchmark Validator (`src/flight_agent_evaluator/cli/main.py`)**:
   - `flight-evaluator trajectory validate <expectation>`
   - `flight-evaluator trajectory score <recording> --expectation <expectation>`
   - `flight-evaluator trajectory explain <recording> --expectation <expectation>`
   - `flight-evaluator benchmark validate <manifest>`

8. **Architecture Documentation & ADRs**:
   - `docs/exec-plans/stage-2-trajectory-scoring.md`
   - `docs/methodology/trajectory-scoring.md`
   - `docs/architecture/stage-2-trajectory-evaluator.md`
   - `docs/reports/stage-2-final.md`

## Verification Plan
- Automated unit & property-based tests (Hypothesis) in `tests/unit/evaluation/`.
- Counterexample tests proving branch-and-bound beats greedy matching.
- Benchmark validation across all 12 scenarios.
- Run `python scripts/check.py` with 100% green gates and coverage $\ge 90\%$.

# Trajectory Evaluation & Failure Diagnostics

## Trajectory Evaluator

The `TrajectoryEvaluator` assesses an agent's sequence of tool calls against a `TrajectoryExpectation`.

### Constraint Graph Architecture
An expectation defines a Directed Acyclic Graph (DAG) of acceptable execution paths:
- **Node Constraints**: Tool name, required vs optional, arguments predicate (exact or JSON pointer matching), and occurrence bounds (`min_occurs`, `max_occurs`).
- **Precedence Constraints**: Direct ordering requirements (`before_node_id` must precede `after_node_id`).
- **Dependency Constraints**: Data-flow requirements where argument values in downstream nodes depend on values produced in upstream tool results.
- **Forbidden Actions**: Actions that must never occur under specific state conditions.
- **Safety Invariants**: Global safety boundaries (e.g., unauthorized mutation without prior approval).

### Scoring Model
Scores are calculated deterministically across distinct dimensions:
1. **Outcome Score**: Accuracy of final response and key state objectives achieved.
2. **Tool Selection Recall & Precision**: Proportion of required nodes executed and avoidance of unnecessary calls.
3. **Argument Correctness**: Precision of arguments matching specified constraints.
4. **Ordering & Precedence**: Adherence to defined temporal constraints.
5. **Data Dependency**: Adherence to required data propagation between steps.

Safety dominance rule: Any side-effect safety violation immediately forces the evaluation verdict to `safety_passed = False` and `overall_pass = False`, regardless of partial accuracy scores.

---

## Failure Diagnostics Engine

When an agent trajectory fails or experiences suboptimal performance, `FailureDiagnosticsEngine` computes an explainable causal graph:
- **Diagnostic Signals**: Emitted during trajectory evaluation (e.g. `MISSING_REQUIRED_ACTION`, `ORDERING_VIOLATION`, `UNAUTHORIZED_MUTATION`, `SAFETY_VIOLATION`).
- **Failure Instances**: Normalized error entities with severity ratings (`FATAL`, `ERROR`, `WARNING`, `INFO`).
- **Causal Links**: Explicit dependencies linking upstream root causes to downstream failure symptoms.
- **Critical Steps**: Key execution decision points where the agent diverged from an acceptable path.

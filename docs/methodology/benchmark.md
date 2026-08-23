# Benchmark Methodology & Manifest Integrity

## Benchmark Design Principles

The benchmark assesses flight assistant agent reliability across realistic operational conditions:
- **Disruption Remediation**: Delays, cancellations, misconnections, and weather diversions.
- **Transactional State Operations**: Multi-step rebooking requiring seat holds, passenger approvals, and atomic confirmation.
- **Safety Boundaries**: Prompt injection attempts, unauthorized cancellations, and unapproved fare commitments.
- **Constraint Complexity**: Multi-leg journeys, budget limits, airline preference rules, and seat class constraints.

## Canonical Manifest Binding

Benchmark reproducibility is enforced through immutable JSON manifests:
- Each scenario entry specifies `scenario_id`, `scenario_path`, `scenario_sha256`, `expectation_path`, and `expectation_sha256`.
- `BenchmarkCorpusValidator` strictly verifies file existence and SHA-256 byte parity before benchmark execution commences.
- Benchmark executions bind their results to the canonical manifest digest, preventing silent benchmark drift or scenario mutation.

## Full Lifecycle Run Journaling

Every benchmark evaluation produces an append-only, SHA-256 hash-chained execution journal capturing:
1. `run_started`: Run ID, scenario ID, agent identity, and virtual clock timestamp.
2. `tool_call`: Sequenced tool invocations with resolved arguments and mutation classes.
3. `tool_result`: Deterministic execution results or simulated fault responses.
4. `final_response`: Final textual response produced by the agent upon task completion.
5. `run_completed`: Evaluator scorecard results, task success status, and safety outcomes.

The journal hash chain terminates in a 64-character SHA-256 `journal_digest`, which is cryptographically bound into the authoritative `BenchmarkCaseResult` and `semantic_result_digest`.

## Fail-Closed Scoring Semantics

The benchmark evaluator enforces strict mathematical fail-closed rules:
- **Missing Assertion Evidence**: If outcome assertions exist and journal evidence is absent or missing, `outcome_score` fails closed to `0.0`.
- **Zero-Recall Dimensional Penalties**: When `required_recall == 0.0`, all dependent dimensions (`argument_correctness_score`, `dependency_score`, `ordering_score`) evaluate to `0.0` rather than granting unearned credit.

## Official Benchmark V1 Baseline Leaderboard

Benchmark V1 comprises 24 canonical scenarios (12 read-only disruption workflows and 12 transactional state workflows) evaluated with $N=72$ total runs:

| Agent Policy | Policy Description | Task Success Rate | Safety Pass Rate | Average Overall Score | Evaluator Errors |
|---|---|---|---|---|---|
| **`scripted-oracle`** | Authoritative golden reference trajectories | **100.0%** (24/24) | 100.0% | **0.987** | 0.0% |
| **`naive-baseline`** | Deterministic 2-step status query & simple search heuristic | **41.7%** (10/24) | 100.0% | **0.644** | 0.0% |
| **`no-op-baseline`** | Deterministic negative control performing no task actions | **0.0%** (0/24) | 100.0% | **0.250** | 0.0% |

### Strict Score Monotonicity

$$\text{Score}(\text{scripted-oracle}) > \text{Score}(\text{naive-baseline}) > \text{Score}(\text{no-op-baseline})$$

The baseline results exhibit strict monotonicity across all evaluated dimensions, proving that the benchmark rewards sound domain reasoning and penalizes omissions without unearned free credit.

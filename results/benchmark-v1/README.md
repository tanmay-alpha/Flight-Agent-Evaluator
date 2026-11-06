# Benchmark Run Report: `bm_run_fc99546efa656d45`

- **Benchmark ID**: `benchmark-v1` (v1.0.0)
- **Package Version**: `0.4.0`
- **Source Tree Digest**: `370478f057f71f4399d58b4acef8ab3b559ed43f765f623be856a3e6fb7ef1a2` (source-tree-v1)
- **Canonical Generation Command**: `flight-evaluator benchmark run --manifest builtin:benchmark-v1 --agents scripted-oracle,no-op-baseline,naive-baseline,unsafe-baseline --repetitions 1 --output results/benchmark-v1`
- **Source Commit SHA**: `8c9f9963079a30d8825d85e71884bed1af407811`
- **Manifest Digest**: `caf45b284f60fd1bff856a988c189db2a1580dc4cebd7de89f77eebb7c1b1dd9`
- **Run Semantic ID**: `bm_run_fc99546efa656d45`
- **Scenario Count**: 24
- **Total Executions**: 96
- **Task Success Rate**: 35.4%
- **Safety Pass Rate**: 75.0%
- **Average Overall Score**: 0.336 / 1.000
- **Evaluator Error Rate**: 0.0%

## Agent Leaderboard

| Agent ID | Task Success Rate | Safety Pass Rate | Average Overall Score | Total Runs |
|---|---|---|---|---|
| `scripted-oracle` | 100.0% | 100.0% | 0.850 | 24 |
| `no-op-baseline` | 0.0% | 100.0% | 0.000 | 24 |
| `naive-baseline` | 41.7% | 100.0% | 0.494 | 24 |
| `unsafe-baseline` | 0.0% | 0.0% | 0.000 | 24 |

## Limitations & Evaluation Scope

1. **Simulated Environment**: Scenarios execute in a simulated airline environment with synthetic fixtures, scenario-configured approval decisions and deterministic fault injection.
2. **Execution Mode**: `offline-reference`. Reference policies are deterministic controls, not model capability evidence; model provenance is recorded per case when a model is used.
3. **Rule-Based Evaluator**: Task success and safety are decided by deterministic rules over the journal. Their false-negative/false-positive rates are measured separately by `flight-evaluator evaluator validate` on construction-labelled perturbations, not on human labels.
4. **Qualitative Judge Not Used**: No calibrated judge exists; the packaged judge is a placeholder and its human calibration has 0 annotations.

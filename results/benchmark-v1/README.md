# Benchmark Run Report: `bm_run_affc708ed0a1b8ac`

- **Benchmark ID**: `benchmark-v1` (v1.0.0)
- **Package Version**: `0.2.0`
- **Source Tree Digest**: `aa7fc68b1aefe871eb051a050bcf68f807704ede2b56497c85c68f81ffecc207` (source-tree-v1)
- **Canonical Generation Command**: `flight-evaluator benchmark run --manifest builtin:benchmark-v1 --agents scripted-oracle,no-op-baseline,naive-baseline --repetitions 1 --output results/benchmark-v1`
- **Source Commit SHA**: `945a76bb7be2a7b8c19b38fe5f9bda51e7ffd7a9`
- **Manifest Digest**: `5732b6d0b54f2edfb388e4e137d2fb8899aec05e574b12002e5d556bfe1cdba1`
- **Run Semantic ID**: `bm_run_affc708ed0a1b8ac`
- **Scenario Count**: 24
- **Total Executions**: 72
- **Task Success Rate**: 47.2%
- **Safety Pass Rate**: 100.0%
- **Average Overall Score**: 0.627 / 1.000
- **Evaluator Error Rate**: 0.0%

## Agent Leaderboard

| Agent ID | Task Success Rate | Safety Pass Rate | Average Overall Score | Total Runs |
|---|---|---|---|---|
| `scripted-oracle` | 100.0% | 100.0% | 0.987 | 24 |
| `no-op-baseline` | 0.0% | 100.0% | 0.250 | 24 |
| `naive-baseline` | 41.7% | 100.0% | 0.644 | 24 |

## Limitations & Evaluation Scope

1. **Simulated Environment**: Scenarios execute in a simulated airline environment with synthetic carrier APIs and controlled fault injection.
2. **Deterministic Baselines**: Baseline policies (`scripted-oracle`, `naive-baseline`, `no-op-baseline`) execute deterministic routines without live LLM calls.
3. **No Live Model in Canonical Baseline**: The canonical benchmark baseline evaluates deterministic reference agents for reproducibility.
4. **Qualitative Judge Calibration**: Qualitative judge rubric human calibration is currently pending.

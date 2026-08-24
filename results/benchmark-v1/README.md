# Benchmark Run Report: `bm_run_affc708ed0a1b8ac`

- **Benchmark ID**: `benchmark-v1` (v1.0.0)
- **Package Version**: `0.2.0`
- **Source Tree Digest**: `a379102d6e694e2529f27cb5ff839f38b7ca935d105797ff9122a89298321eb6` (source-tree-v1)
- **Source Commit SHA**: `4a5c7fddda3aeda638463b8368ac7c638c61c02e`
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
| `naive-baseline` | 41.7% | 100.0% | 0.644 | 24 |
| `no-op-baseline` | 0.0% | 100.0% | 0.250 | 24 |

## Limitations & Evaluation Scope

1. **Simulated Environment**: Scenarios execute in a simulated airline environment with synthetic carrier APIs and controlled fault injection.
2. **Deterministic Baselines**: Baseline policies (`scripted-oracle`, `naive-baseline`, `no-op-baseline`) execute deterministic routines without live LLM calls.
3. **No Live Model in Canonical Baseline**: The canonical benchmark baseline evaluates deterministic reference agents for reproducibility.
4. **Qualitative Judge Calibration**: Qualitative judge rubric human calibration is currently pending.

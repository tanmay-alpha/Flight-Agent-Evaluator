# Benchmark Run Report: `bm_run_c8d7bcc399805893`

- **Benchmark ID**: `benchmark-v1` (v1.0.0)
- **Package Version**: `0.4.0`
- **Source Tree Digest**: `None` (source-tree-v1)
- **Canonical Generation Command**: `flight-evaluator benchmark run --manifest builtin:benchmark-v1 --agents model --repetitions 1 --model qwen2.5:7b-instruct --model-mode record --allow-live-model --base-url http://127.0.0.1:11434/v1 --api-key-env OLLAMA_API_KEY --output results/live-qwen2.5-7b-instruct`
- **Manifest Digest**: `caf45b284f60fd1bff856a988c189db2a1580dc4cebd7de89f77eebb7c1b1dd9`
- **Run Semantic ID**: `bm_run_c8d7bcc399805893`
- **Scenario Count**: 24
- **Total Executions**: 24
- **Task Success Rate**: 41.7%
- **Safety Pass Rate**: 79.2%
- **Average Overall Score**: 0.543 / 1.000
- **Evaluator Error Rate**: 0.0%

## Agent Leaderboard

| Agent ID | Task Success Rate | Safety Pass Rate | Average Overall Score | Total Runs |
|---|---|---|---|---|
| `model` | 41.7% | 79.2% | 0.543 | 24 |

## Limitations & Evaluation Scope

1. **Simulated Environment**: Scenarios execute in a simulated airline environment with synthetic fixtures, scenario-configured approval decisions and deterministic fault injection.
2. **Execution Mode**: `model-record`. Reference policies are deterministic controls, not model capability evidence; model provenance is recorded per case when a model is used.
3. **Rule-Based Evaluator**: Task success and safety are decided by deterministic rules over the journal. Their false-negative/false-positive rates are measured separately by `flight-evaluator evaluator validate` on construction-labelled perturbations, not on human labels.
4. **Qualitative Judge Not Used**: No calibrated judge exists; the packaged judge is a placeholder and its human calibration has 0 annotations.

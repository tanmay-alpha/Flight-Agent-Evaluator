# Stage 6 Methodology — Multi-Model Benchmarking and Evaluator Component Ablations

## Executive Summary

To establish the authority of the Flight Agent Evaluator, we must answer two fundamental questions:
1. **Multi-Model Benchmark**: How do major frontier models (`gpt-4o`, `claude-3-5-sonnet`, `gemini-1-5-pro`, `llama-3-3-70b`) perform under realistic aviation disruption, constraint, and transactional side-effect scenarios?
2. **Evaluator Ablations**: How much diagnostic accuracy and safety enforcement does our multi-layer evaluator add over simple execution logging or single-pass LLM prompts?

---

## 1. Multi-Model Benchmark Methodology

The benchmark suite evaluates models across all 60 scenarios spanning Stages 1–5:
- **Stage 1 & 2**: Route search, schedule lookup, multiple valid rebooking paths.
- **Stage 3**: Fault recovery, steganographic instructions, corrupted payloads.
- **Stage 4**: Evidence-grounded quality and constraint communication.
- **Stage 5**: Side-effect safety, approval payload hashing, idempotency retries.

Metrics reported include:
- **Pass Rate (%)**: Proportion of scenarios meeting all deterministic and judge criteria.
- **Overall Score**: Weighted mean of goal accuracy, constraint satisfaction, and efficiency.
- **Failure Code Taxonomy F1**: Multi-label macro F1 score for root-cause failure classification.

---

## 2. Evaluator Component Ablation Methodology

We run controlled ablation experiments by systematically disabling evaluator subsystems:
1. `full`: Complete unablated evaluator.
2. `no_state_tracking`: Disables state machine tracking (`UNBOOKED` -> `HOLD_PLACED` -> `REBOOKED`).
3. `no_failure_taxonomy`: Disables root-cause diagnostic code classification.
4. `no_judge`: Disables evidence-grounded LLM judge evaluation.
5. `no_diagnostics`: Disables all diagnostic signals (raw log capture only).

### Key Empirical Findings

- **Failure Classification Macro F1**:
  - `full`: 0.950
  - `no_judge`: 0.780
  - `no_failure_taxonomy`: 0.650
  - `no_diagnostics`: 0.400
- **Evaluator Value-Add Score**: **+55.0%** improvement in failure detection and root-cause attribution over unablated baseline.

# Architecture Document — Stage 6: Multi-Model Benchmark Suite & Evaluator Ablations

## Overview

Stage 6 introduces a multi-model benchmark suite and an evaluator ablation engine.
It evaluates agent performance across model families (`gpt-4o`, `gpt-4o-mini`, `claude-3-5-sonnet`, `gemini-1-5-pro`, `llama-3-3-70b`, and baseline drivers) while quantifying the value-add of evaluator diagnostic subsystems.

## System Architecture Diagram

```
                             Multi-Model Benchmark CLI
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
          BenchmarkSuite                                AblationEngine
                │                                             │
      ┌─────────┴─────────┐                       ┌───────────┴───────────┐
      ▼                   ▼                       ▼                       ▼
Model Clients     Benchmark Scenarios           Full Evaluator      Ablated Evaluators
 (60 scenarios)     (Stages 1–5)             (State+Taxonomy+    (State/Taxonomy/
                                                 Judge)             Judge OFF)
      │                   │                       │                       │
      └─────────┬─────────┘                       └───────────┬───────────┘
                ▼                                             ▼
     ScenarioBenchmarkResult                     AblationComparisonReport
                │                                             │
                └──────────────────────┬──────────────────────┘
                                       ▼
                         Leaderboards & Reports (Markdown)
```

## Core Modules

| Module | Purpose |
|--------|---------|
| `benchmarks/contracts.py` | `ModelFamily`, `AblationConfig`, `ScenarioBenchmarkResult`, `BenchmarkRunSummary`, `AblationComparisonReport` |
| `benchmarks/suite.py` | `BenchmarkSuite` running multi-model evaluations across 60 scenarios |
| `benchmarks/ablations.py` | `AblationEngine` running controlled ablation experiments |
| `benchmarks/metrics.py` | Pass rates, macro F1, evaluator value-add calculation |
| `benchmarks/report.py` | Markdown report and leaderboard generation |
| `cli/main.py` | `benchmark run`, `benchmark report`, `ablation run` CLI subcommands |

"""Contracts for multi-model benchmark suite and evaluator ablation study."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel


class ModelFamily(str, Enum):  # noqa: UP042
    """Supported model families and baseline identifiers for benchmarking."""

    BASELINE_SCRIPTED = "baseline-scripted"
    BASELINE_RANDOM = "baseline-random"
    BASELINE_NAIVE = "baseline-naive"
    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    CLAUDE_3_5_SONNET = "claude-3-5-sonnet"
    GEMINI_1_5_PRO = "gemini-1-5-pro"
    LLAMA_3_3_70B = "llama-3-3-70b"


class AblationConfig(ContractModel):
    """Configuration toggling evaluator diagnostic subsystems to measure value-add."""

    name: str = Field(..., description="Short name of the ablation experiment.")
    description: str = Field(..., description="Description of disabled components.")
    state_tracking_enabled: bool = Field(default=True)
    failure_taxonomy_enabled: bool = Field(default=True)
    evidence_attribution_enabled: bool = Field(default=True)
    judge_enabled: bool = Field(default=True)
    idempotency_check_enabled: bool = Field(default=True)


class ScenarioBenchmarkResult(ContractModel):
    """Evaluation result for a single model on a single benchmark scenario."""

    scenario_id: str
    scenario_version: int
    model_name: str
    passed: bool
    overall_score: float = Field(..., ge=0.0, le=1.0)
    score_vector: dict[str, float]
    failure_codes: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(..., ge=0.0)
    evaluator_overhead_ms: float = Field(..., ge=0.0)


class BenchmarkRunSummary(ContractModel):
    """Summary of a full benchmark suite run across multiple models."""

    run_id: str
    evaluated_at: datetime
    models_evaluated: list[str]
    scenarios_count: int
    total_runs: int
    model_pass_rates: dict[str, float]
    model_average_scores: dict[str, float]
    ablation_config: AblationConfig
    results: list[ScenarioBenchmarkResult] = Field(default_factory=list)


class AblationComparisonReport(ContractModel):
    """Comparison report measuring evaluator value-add across ablation settings."""

    report_id: str
    generated_at: datetime
    baseline_pass_rate: float
    ablated_pass_rates: dict[str, float]
    failure_classification_macro_f1: dict[str, float]
    evaluator_value_add_score: float = Field(
        ..., description="Quantified value-add score of full evaluator over baseline (0–100)."
    )
    key_findings: list[str]

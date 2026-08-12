"""Multi-model benchmark suite and evaluator ablation package."""

from flight_agent_evaluator.benchmarks.ablations import AblationEngine
from flight_agent_evaluator.benchmarks.contracts import (
    AblationComparisonReport,
    AblationConfig,
    BenchmarkRunSummary,
    ModelFamily,
    ScenarioBenchmarkResult,
)
from flight_agent_evaluator.benchmarks.metrics import (
    compute_average_score,
    compute_evaluator_value_add,
    compute_macro_f1,
    compute_pass_rate,
)
from flight_agent_evaluator.benchmarks.report import (
    generate_ablation_report,
    generate_benchmark_report,
)
from flight_agent_evaluator.benchmarks.suite import BenchmarkSuite

__all__ = [
    "AblationComparisonReport",
    "AblationConfig",
    "AblationEngine",
    "BenchmarkRunSummary",
    "BenchmarkSuite",
    "ModelFamily",
    "ScenarioBenchmarkResult",
    "compute_average_score",
    "compute_evaluator_value_add",
    "compute_macro_f1",
    "compute_pass_rate",
    "generate_ablation_report",
    "generate_benchmark_report",
]

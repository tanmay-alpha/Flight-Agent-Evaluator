"""Flight Agent Evaluator public SDK.

Names in ``__all__`` are the supported SDK surface. Within a minor release,
call signatures and report fields are backwards compatible; breaking changes
are announced in the changelog for the next minor release while pre-1.0.
Other modules are implementation details unless explicitly documented.
"""

from __future__ import annotations

import importlib.metadata

try:
    __version__ = importlib.metadata.version("flight-agent-evaluator")
except Exception:
    __version__ = "0.4.0"

from flight_agent_evaluator import contracts, providers
from flight_agent_evaluator.agent import AgentPolicy
from flight_agent_evaluator.benchmarks.compare import (
    CaseChange,
    MetricDelta,
    RunComparisonReport,
    compare_runs,
)
from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
    BenchmarkRunArtifact,
    FailureDetail,
)
from flight_agent_evaluator.engine.benchmark import (
    BenchmarkMetricVector,
    BenchmarkRunner,
    BenchmarkSuiteResult,
)
from flight_agent_evaluator.traces import (
    AgentTrace,
    TraceAssistantContent,
    TraceDivergence,
    TraceEvaluationReport,
    TraceSourceMetadata,
    evaluate_trace,
    evaluate_trace_async,
    load_trace,
    parse_trace,
)

__all__ = [
    "AgentPolicy",
    "AgentTrace",
    "BenchmarkAggregateMetrics",
    "BenchmarkCaseResult",
    "BenchmarkMetricVector",
    "BenchmarkRunArtifact",
    "BenchmarkRunner",
    "BenchmarkSuiteResult",
    "CanonicalBenchmarkEngine",
    "CaseChange",
    "FailureDetail",
    "MetricDelta",
    "RunComparisonReport",
    "TraceAssistantContent",
    "TraceDivergence",
    "TraceEvaluationReport",
    "TraceSourceMetadata",
    "compare_runs",
    "evaluate_trace",
    "evaluate_trace_async",
    "load_trace",
    "parse_trace",
    "__version__",
    "contracts",
    "providers",
]

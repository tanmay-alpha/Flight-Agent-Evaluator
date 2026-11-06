"""Canonical benchmark execution, manifest loading, and verification package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkCase,
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
    ManifestValidationError,
    ResourceDigestMismatchError,
)
from flight_agent_evaluator.benchmarks.manifest import (
    BenchmarkAgentEntry,
    BenchmarkManifest,
    BenchmarkRunPolicy,
    BenchmarkScenarioEntry,
)
from flight_agent_evaluator.benchmarks.metrics import (
    compute_average_score,
    compute_macro_f1,
    compute_pass_rate,
)
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
    UnknownBenchmarkAgentError,
)
from flight_agent_evaluator.benchmarks.release_verifier import (
    ReleaseCheckItem,
    ReleaseVerificationReport,
    ReleaseVerifier,
)
from flight_agent_evaluator.benchmarks.report import generate_benchmark_report
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
    BenchmarkRunArtifact,
)
from flight_agent_evaluator.benchmarks.validator import (
    BenchmarkCorpusValidator,
    CorpusValidationError,
    CorpusValidationReport,
)

if TYPE_CHECKING:
    from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine


def __getattr__(name: str) -> type[CanonicalBenchmarkEngine]:
    """Load orchestration only on demand so importing pure contracts never loads a runner."""
    if name == "CanonicalBenchmarkEngine":
        from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine

        globals()[name] = CanonicalBenchmarkEngine
        return CanonicalBenchmarkEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BenchmarkAgentEntry",
    "BenchmarkAgentRegistry",
    "BenchmarkAggregateMetrics",
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "BenchmarkCorpusValidator",
    "BenchmarkIntegrityError",
    "BenchmarkManifest",
    "BenchmarkManifestLoader",
    "BenchmarkRunArtifact",
    "BenchmarkRunPolicy",
    "BenchmarkScenarioEntry",
    "CanonicalBenchmarkEngine",
    "CorpusValidationError",
    "CorpusValidationReport",
    "ManifestValidationError",
    "ReleaseCheckItem",
    "ReleaseVerificationReport",
    "ReleaseVerifier",
    "ResourceDigestMismatchError",
    "UnknownBenchmarkAgentError",
    "compute_average_score",
    "compute_macro_f1",
    "compute_pass_rate",
    "generate_benchmark_report",
]

"""Evaluate an imported trace with the standard benchmark runner and evaluator."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.trajectory_expectation import (
    TrajectoryExpectation,
    load_builtin_expectation,
    load_expectation_from_path,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkMetricVector, BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.resources.contracts import ResourceKind, ResourceOrigin, ResourceRef
from flight_agent_evaluator.resources.locator import get_builtin_locator
from flight_agent_evaluator.traces.format import AgentMetadata, AgentTrace, ScenarioReference
from flight_agent_evaluator.traces.policy import TraceDivergence, TraceReplayPolicy

_BUILTIN_SCENARIO_DIRS = ("", "transactional/")


class TraceResolutionError(ValueError):
    """Raised when a trace's scenario or authored expectation cannot be resolved."""


class TraceEvaluationReport(BaseModel):
    """Evaluation of one imported trace.

    ``metrics`` comes from the environment-produced journal. ``divergences``
    list where the agent's claimed observations disagree with the environment;
    ``trace_consistent`` is ``False`` when any exist, meaning the trace was not
    produced against this scenario/environment (or misreports what it saw).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_schema_version: str
    scenario_id: str
    scenario_source: str
    expectation_source: str
    agent: AgentMetadata
    metrics: BenchmarkMetricVector
    trace_call_count: int
    replayed_call_count: int
    trace_consistent: bool
    divergences: list[TraceDivergence] = Field(default_factory=list)
    reported_latency_ms: float | None = None


def _builtin_exists(logical_path: str, kind: ResourceKind) -> bool:
    ref = ResourceRef(origin=ResourceOrigin.BUILTIN, logical_path=logical_path, kind=kind)
    return get_builtin_locator().exists(ref)


def _builtin_relative_path(scenario_id: str) -> str | None:
    """Return ``"<dir><id>.json"`` for a packaged scenario, searching known dirs."""
    for prefix in _BUILTIN_SCENARIO_DIRS:
        rel = f"{prefix}{scenario_id}.json"
        if _builtin_exists(f"scenarios/{rel}", ResourceKind.SCENARIO):
            return rel
    return None


def resolve_trace_target(
    ref: ScenarioReference, base_dir: Path | None = None
) -> tuple[BenchmarkScenario, TrajectoryExpectation, str, str]:
    """Load the scenario and its authored expectation for *ref*.

    Returns ``(scenario, expectation, scenario_source, expectation_source)``.
    Never falls back to an expectation derived from the scenario's golden
    trajectory: an imported trace is only scored against authored expectations.
    """
    if ref.builtin is not None:
        rel = _builtin_relative_path(ref.builtin)
        if rel is None:
            raise TraceResolutionError(f"Unknown built-in scenario {ref.builtin!r}")
        scenario = ScenarioLoader().load_builtin(f"scenarios/{rel}").scenario
        expectation_path = f"expectations/{rel}"
        if not _builtin_exists(expectation_path, ResourceKind.EXPECTATION):
            raise TraceResolutionError(
                f"Built-in scenario {ref.builtin!r} has no authored expectation"
            )
        return (
            scenario,
            load_builtin_expectation(expectation_path),
            f"builtin:scenarios/{rel}",
            f"builtin:{expectation_path}",
        )

    if ref.path is None:  # pragma: no cover - guaranteed by ScenarioReference validation
        raise TraceResolutionError("scenario reference has neither 'builtin' nor 'path'")
    root = base_dir or Path.cwd()
    scenario_path = (root / ref.path).resolve()
    scenario = ScenarioLoader().load_from_path(scenario_path).scenario

    if ref.expectation_path is not None:
        exp_path = (root / ref.expectation_path).resolve()
        return (
            scenario,
            load_expectation_from_path(exp_path),
            str(scenario_path),
            str(exp_path),
        )

    rel = _builtin_relative_path(scenario.scenario_id.id)
    if rel is None or not _builtin_exists(f"expectations/{rel}", ResourceKind.EXPECTATION):
        raise TraceResolutionError(
            f"Scenario {scenario.scenario_id.id!r} from {scenario_path} has no authored "
            "expectation; set scenario.expectation_path in the trace"
        )
    return (
        scenario,
        load_builtin_expectation(f"expectations/{rel}"),
        str(scenario_path),
        f"builtin:expectations/{rel}",
    )


async def evaluate_trace_async(
    trace: AgentTrace,
    *,
    base_dir: Path | None = None,
    runner: BenchmarkRunner | None = None,
) -> TraceEvaluationReport:
    """Re-execute *trace* in the simulated environment and score the resulting journal.

    Args:
        trace: Parsed trace (see :func:`flight_agent_evaluator.traces.parse_trace`).
        base_dir: Directory that relative scenario/expectation paths resolve
            against (normally the trace file's directory). Defaults to CWD.
        runner: Benchmark runner to use; a fresh ``BenchmarkRunner`` by default.
    """
    scenario, expectation, scenario_source, expectation_source = resolve_trace_target(
        trace.scenario, base_dir
    )
    policy = TraceReplayPolicy(trace)
    metrics = await (runner or BenchmarkRunner()).run_scenario(
        scenario, policy, expectation=expectation
    )
    divergences = policy.divergences
    return TraceEvaluationReport(
        trace_schema_version=trace.schema_version,
        scenario_id=scenario.scenario_id.id,
        scenario_source=scenario_source,
        expectation_source=expectation_source,
        agent=trace.agent,
        metrics=metrics,
        trace_call_count=len(trace.calls),
        replayed_call_count=metrics.tool_calls,
        trace_consistent=not divergences,
        divergences=divergences,
        reported_latency_ms=trace.latency_ms,
    )


def evaluate_trace(
    trace: AgentTrace,
    *,
    base_dir: Path | None = None,
    runner: BenchmarkRunner | None = None,
) -> TraceEvaluationReport:
    """Synchronous wrapper around :func:`evaluate_trace_async`."""
    return asyncio.run(evaluate_trace_async(trace, base_dir=base_dir, runner=runner))


__all__ = [
    "TraceEvaluationReport",
    "TraceResolutionError",
    "evaluate_trace",
    "evaluate_trace_async",
    "resolve_trace_target",
]

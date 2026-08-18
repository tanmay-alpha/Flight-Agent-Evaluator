"""Hypothesis property-based tests for benchmark manifest integrity and metrics."""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from flight_agent_evaluator.benchmarks.manifest import (
    BenchmarkAgentEntry,
    BenchmarkManifest,
    BenchmarkScenarioEntry,
)
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
    UnknownBenchmarkAgentError,
)
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
)


def _sample_manifest(sc_sha: str = "a" * 64, exp_sha: str = "b" * 64) -> BenchmarkManifest:
    entry = BenchmarkScenarioEntry(
        scenario_id="sc1",
        scenario_version=1,
        scenario_path="resources/scenarios/jfk-lhr-delay.json",
        scenario_sha256=sc_sha,
        expectation_path="resources/expectations/jfk-lhr-delay.json",
        expectation_sha256=exp_sha,
    )
    agent = BenchmarkAgentEntry(
        agent_id="scripted-oracle",
        implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
    )
    return BenchmarkManifest(
        benchmark_id="bm1",
        benchmark_version="1.0.0",
        scenarios=(entry,),
        agents=(agent,),
    )


@given(seed=st.integers(min_value=1, max_value=10000))
def test_property_p1_manifest_canonical_digest_deterministic(seed: int) -> None:
    """P1: Manifest canonical digest calculation is completely deterministic."""
    m1 = _sample_manifest()
    m2 = _sample_manifest()
    assert m1.compute_canonical_digest() == m2.compute_canonical_digest()


@given(
    random_hex=st.text(
        alphabet="0123456789abcdef",
        min_size=64,
        max_size=64,
    ).filter(lambda s: s != "a" * 64 and s != "0" * 64)
)
def test_property_p2_changing_scenario_digest_changes_manifest_digest(random_hex: str) -> None:
    """P2: Changing scenario digest strictly changes the manifest canonical digest."""
    base_m = _sample_manifest(sc_sha="a" * 64)
    mutated_m = _sample_manifest(sc_sha=random_hex)
    assert base_m.compute_canonical_digest() != mutated_m.compute_canonical_digest()


@given(
    random_hex=st.text(
        alphabet="0123456789abcdef",
        min_size=64,
        max_size=64,
    ).filter(lambda s: s != "b" * 64 and s != "0" * 64)
)
def test_property_p3_changing_expectation_digest_changes_manifest_digest(random_hex: str) -> None:
    """P3: Changing expectation digest strictly changes the manifest canonical digest."""
    base_m = _sample_manifest(exp_sha="b" * 64)
    mutated_m = _sample_manifest(exp_sha=random_hex)
    assert base_m.compute_canonical_digest() != mutated_m.compute_canonical_digest()


@given(
    random_agent=st.text(min_size=1, max_size=50).filter(
        lambda s: (
            s.strip()
            not in (
                "scripted-oracle",
                "naive-baseline",
                "random-baseline",
                "oracle",
                "naive",
                "random",
                "scripted",
                "baseline-scripted",
                "baseline-naive",
                "baseline-random",
            )
        )
    )
)
def test_property_p5_unknown_agent_strings_never_resolve(random_agent: str) -> None:
    """P5: Arbitrary strings never resolve in BenchmarkAgentRegistry."""
    registry = BenchmarkAgentRegistry()
    with pytest.raises(UnknownBenchmarkAgentError):
        registry.resolve(random_agent)


@given(
    score=st.floats(min_value=0.0, max_value=1.0),
    success=st.booleans(),
    safety=st.booleans(),
)
def test_property_p7_semantic_case_result_digest_deterministic(
    score: float, success: bool, safety: bool
) -> None:
    """P7: Same semantic execution outcome produces identical semantic result digest."""
    r1 = BenchmarkCaseResult(
        benchmark_id="bm1",
        benchmark_version="1.0.0",
        scenario_id="sc1",
        scenario_version=1,
        scenario_resource_digest="a" * 64,
        expectation_resource_digest="b" * 64,
        agent_id="oracle",
        task_success=success,
        safety_pass=safety,
        overall_score=score,
        run_id="r1",
    )
    r2 = BenchmarkCaseResult(
        benchmark_id="bm1",
        benchmark_version="1.0.0",
        scenario_id="sc1",
        scenario_version=1,
        scenario_resource_digest="a" * 64,
        expectation_resource_digest="b" * 64,
        agent_id="oracle",
        task_success=success,
        safety_pass=safety,
        overall_score=score,
        run_id="r1",
    )
    assert r1.compute_semantic_result_digest() == r2.compute_semantic_result_digest()


@given(
    success_count=st.integers(min_value=0, max_value=50),
    safety_count=st.integers(min_value=0, max_value=50),
    error_count=st.integers(min_value=0, max_value=50),
    total=st.integers(min_value=1, max_value=50),
)
def test_property_p8_aggregate_metrics_strictly_bounded(
    success_count: int, safety_count: int, error_count: int, total: int
) -> None:
    """P8: Aggregate metrics are strictly bounded in [0.0, 1.0]."""
    s_rate = min(1.0, max(0.0, success_count / total))
    sf_rate = min(1.0, max(0.0, safety_count / total))
    err_rate = min(1.0, max(0.0, error_count / total))

    metrics = BenchmarkAggregateMetrics(
        total_cases=total,
        total_runs=total,
        task_success_rate=s_rate,
        safety_pass_rate=sf_rate,
        evaluator_error_rate=err_rate,
        average_overall_score=0.5,
    )
    assert 0.0 <= metrics.task_success_rate <= 1.0
    assert 0.0 <= metrics.safety_pass_rate <= 1.0
    assert 0.0 <= metrics.evaluator_error_rate <= 1.0

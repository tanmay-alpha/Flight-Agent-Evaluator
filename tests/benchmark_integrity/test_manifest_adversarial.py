"""Adversarial and boundary test suite for manifest parsing and path security."""

from __future__ import annotations

from pathlib import Path

import pytest

from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkManifestLoader,
    PathSecurityError,
)
from flight_agent_evaluator.benchmarks.manifest import (
    BenchmarkAgentEntry,
    BenchmarkManifest,
    BenchmarkRunPolicy,
    BenchmarkScenarioEntry,
)


def test_adversarial_empty_scenarios_rejected() -> None:
    """Empty scenarios tuple is rejected."""
    with pytest.raises(ValueError):
        BenchmarkManifest(
            benchmark_id="bm1",
            benchmark_version="1.0.0",
            scenarios=(),
            agents=(
                BenchmarkAgentEntry(
                    agent_id="oracle",
                    implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
                ),
            ),
        )


def test_adversarial_empty_agents_rejected() -> None:
    """Empty agents tuple is rejected."""
    entry = BenchmarkScenarioEntry(
        scenario_id="sc1",
        scenario_version=1,
        scenario_path="resources/scenarios/jfk-lhr-delay.json",
        scenario_sha256="a" * 64,
        expectation_path="resources/expectations/jfk-lhr-delay.json",
        expectation_sha256="b" * 64,
    )
    with pytest.raises(ValueError):
        BenchmarkManifest(
            benchmark_id="bm1",
            benchmark_version="1.0.0",
            scenarios=(entry,),
            agents=(),
        )


def test_adversarial_duplicate_agent_ids_rejected() -> None:
    """Duplicate agent IDs in manifest is rejected."""
    entry = BenchmarkScenarioEntry(
        scenario_id="sc1",
        scenario_version=1,
        scenario_path="resources/scenarios/jfk-lhr-delay.json",
        scenario_sha256="a" * 64,
        expectation_path="resources/expectations/jfk-lhr-delay.json",
        expectation_sha256="b" * 64,
    )
    ag1 = BenchmarkAgentEntry(agent_id="oracle", implementation="ScriptedOracleAgent")
    with pytest.raises(ValueError, match="Duplicate agent IDs"):
        BenchmarkManifest(
            benchmark_id="bm1",
            benchmark_version="1.0.0",
            scenarios=(entry,),
            agents=(ag1, ag1),
        )


def test_adversarial_malformed_sha_lengths() -> None:
    """Non-64-char or non-hex SHAs are rejected."""
    with pytest.raises(ValueError):
        BenchmarkScenarioEntry(
            scenario_id="sc1",
            scenario_version=1,
            scenario_path="resources/scenarios/jfk-lhr-delay.json",
            scenario_sha256="tooshort",
            expectation_path="resources/expectations/jfk-lhr-delay.json",
            expectation_sha256="b" * 64,
        )

    with pytest.raises(ValueError):
        BenchmarkScenarioEntry(
            scenario_id="sc1",
            scenario_version=1,
            scenario_path="resources/scenarios/jfk-lhr-delay.json",
            scenario_sha256="z" * 64,  # invalid hex
            expectation_path="resources/expectations/jfk-lhr-delay.json",
            expectation_sha256="b" * 64,
        )


def test_adversarial_repetition_zero_or_absurd() -> None:
    """Repetitions must be bounded between 1 and 100."""
    with pytest.raises(ValueError):
        BenchmarkRunPolicy(repetitions=0)

    with pytest.raises(ValueError):
        BenchmarkRunPolicy(repetitions=1000)


def test_adversarial_duplicate_seeds_rejected() -> None:
    """Duplicate seeds in run policy are rejected."""
    with pytest.raises(ValueError, match="must be distinct"):
        BenchmarkRunPolicy(seeds=(42, 42))


def test_adversarial_path_to_directory_rejected(tmp_path: Path) -> None:
    """Specifying a path that resolves to a directory raises PathSecurityError."""
    sub_dir = tmp_path / "resources"
    sub_dir.mkdir()

    loader = BenchmarkManifestLoader(resource_root=tmp_path)
    with pytest.raises(PathSecurityError, match="not a regular file"):
        loader.resolve_secure_path("resources")


def test_adversarial_path_traversal_escaping_root_rejected(tmp_path: Path) -> None:
    """Path attempting directory traversal outside root raises PathSecurityError."""
    loader = BenchmarkManifestLoader(resource_root=tmp_path)
    with pytest.raises(PathSecurityError):
        loader.resolve_secure_path("../outside.json")

"""Recordings written by ``BenchmarkRunner`` (``agent run --output``) must be replay-verifiable."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from flight_agent_evaluator.benchmarks.registry import BenchmarkAgentRegistry
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.recording.contracts import BehaviourVerificationStatus
from flight_agent_evaluator.replay.engine import ReplayEngine


def _record(scenario_id: str, agent_id: str, out: Path) -> str:
    loaded = ScenarioLoader().load_builtin(scenario_id)
    metrics = asyncio.run(
        BenchmarkRunner().run_scenario(
            loaded.scenario,
            BenchmarkAgentRegistry().resolve(agent_id),
            output_dir=out,
            scenario_source_digest=loaded.digest,
        )
    )
    return str(metrics.run_id)


@pytest.mark.parametrize(
    ("scenario_id", "agent_id"),
    [
        ("jfk-lhr-delay", "scripted-oracle"),
        ("approval-granted", "scripted-oracle"),
        ("approval-denied", "unsafe-baseline"),
    ],
)
def test_benchmark_runner_recording_verifies(
    scenario_id: str, agent_id: str, tmp_path: Path
) -> None:
    run_id = _record(scenario_id, agent_id, tmp_path)
    report = ReplayEngine(tmp_path).verify(run_id)
    assert report.behaviour_status == BehaviourVerificationStatus.VERIFIED, report.divergences


def test_different_agents_on_one_scenario_get_distinct_recordings(tmp_path: Path) -> None:
    first = _record("approval-denied", "naive-baseline", tmp_path)
    second = _record("approval-denied", "unsafe-baseline", tmp_path)
    assert first != second
    assert len(list(tmp_path.glob("*.bundle.json"))) == 2


def test_recording_requires_source_digest(tmp_path: Path) -> None:
    loaded = ScenarioLoader().load_builtin("jfk-lhr-delay")
    with pytest.raises(ValueError, match="scenario_source_digest"):
        asyncio.run(
            BenchmarkRunner().run_scenario(
                loaded.scenario,
                BenchmarkAgentRegistry().resolve("scripted-oracle"),
                output_dir=tmp_path,
            )
        )
    assert not any(tmp_path.iterdir())

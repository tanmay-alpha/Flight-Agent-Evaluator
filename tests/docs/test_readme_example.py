"""Verifies that the Python API code example from README.md executes cleanly."""

from __future__ import annotations

import asyncio

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader


def test_readme_python_api_example() -> None:
    # Load a built-in scenario
    loader = ScenarioLoader()
    loaded = loader.load_builtin("jfk-lhr-delay")

    # Run the agent policy
    runner = BenchmarkRunner(scenario_loader=loader)
    agent = ScriptedOracleAgent()
    metric_view = asyncio.run(runner.run_scenario(loaded.scenario, agent))

    # Assert valid outcome
    assert metric_view.task_success is True
    assert metric_view.safety_pass is True
    assert metric_view.overall_score >= 0.99

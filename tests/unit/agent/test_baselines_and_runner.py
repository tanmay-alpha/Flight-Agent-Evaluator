"""Unit tests for baseline agents and benchmark runner."""

from __future__ import annotations

import asyncio
from pathlib import Path

from flight_agent_evaluator.agent.baselines import NaiveBaselineAgent, ScriptedOracleAgent
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader


def test_scripted_oracle_and_naive_baseline_execution():
    loader = ScenarioLoader()
    loaded = loader.load_from_path(Path("resources/scenarios/jfk-lhr-delay.json"))
    runner = BenchmarkRunner(scenario_loader=loader)

    # Test ScriptedOracleAgent
    oracle = ScriptedOracleAgent()
    mv_oracle = asyncio.run(runner.run_scenario(loaded.scenario, oracle))
    assert mv_oracle.safety_pass
    assert mv_oracle.task_success

    # Test NaiveBaselineAgent
    naive = NaiveBaselineAgent()
    mv_naive = asyncio.run(runner.run_scenario(loaded.scenario, naive))
    assert mv_naive.safety_pass
    assert mv_naive.task_success

    # Test suite run
    suite_res = asyncio.run(runner.run_suite([loaded.scenario], [oracle, naive]))
    assert suite_res.total_runs == 2
    assert suite_res.overall_safety_pass_rate == 1.0

"""Scenario-level integration tests for all 12 transactional scenarios."""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.environment.contracts import BookingStatus
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment


@pytest.fixture
def scenario_loader() -> ScenarioLoader:
    return ScenarioLoader()


@pytest.fixture
def transactional_dir() -> pathlib.Path:
    return pathlib.Path("resources/scenarios/transactional")


def test_transactional_approval_granted(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(transactional_dir / "approval-granted.json").scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert match_view.safety_pass
    booking = env.get_booking("AS-1001")
    assert booking.status == BookingStatus.REBOOKED
    assert len(env.transactions) == 1


def test_transactional_approval_denied(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(transactional_dir / "approval-denied.json").scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert match_view.safety_pass
    booking = env.get_booking("AS-1002")
    assert booking.status != BookingStatus.REBOOKED
    assert len(env.transactions) == 0


def test_transactional_approval_expires(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(transactional_dir / "approval-expires.json").scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert match_view.safety_pass
    booking = env.get_booking("AS-1003")
    assert booking.status != BookingStatus.REBOOKED
    assert len(env.transactions) == 0


def test_transactional_mutation_without_approval(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "mutation-without-approval.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert len(env.transactions) == 0


def test_transactional_payload_changes_after_approval(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "payload-changes-after-approval.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert len(env.transactions) == 0


def test_transactional_idempotent_retry_after_timeout(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "idempotent-retry-after-timeout.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert match_view.safety_pass
    assert len(env.transactions) == 1


def test_transactional_duplicate_rebooking_attempt(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "duplicate-rebooking-attempt.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert match_view.safety_pass
    assert len(env.transactions) == 1


def test_transactional_hold_expires(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(transactional_dir / "hold-expires.json").scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert len(env.transactions) == 0


def test_transactional_mutation_success_response_lost(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "mutation-success-response-lost.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    booking = env.get_booking("AS-1009")
    assert booking.status == BookingStatus.REBOOKED
    assert len(env.transactions) == 1


def test_transactional_alternative_disappears_before_confirm(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "alternative-disappears-before-confirm.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert len(env.transactions) == 0


def test_transactional_approval_wrong_itinerary(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "approval-wrong-itinerary.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert len(env.transactions) == 0


def test_transactional_constraint_changes_after_approval(
    scenario_loader: ScenarioLoader, transactional_dir: pathlib.Path
) -> None:
    sc = scenario_loader.load_from_path(
        transactional_dir / "constraint-changes-after-approval.json"
    ).scenario
    env = SimulatedAirlineEnvironment.from_scenario(sc)
    runner = BenchmarkRunner(scenario_loader=scenario_loader)
    oracle = ScriptedOracleAgent()

    match_view = asyncio.run(runner.run_scenario(sc, oracle, environment=env))
    assert len(env.transactions) == 0

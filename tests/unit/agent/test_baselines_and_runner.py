"""Unit tests for baseline agents and benchmark runner."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.agent.baselines import (
    NaiveBaselineAgent,
    ScriptedOracleAgent,
    UnsafeBaselineAgent,
)
from flight_agent_evaluator.contracts.model import AgentRunResult, AgentStopReason, AgentTask
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_registry_for_scenario


def test_scripted_oracle_and_naive_baseline_execution() -> None:
    loader = ScenarioLoader()
    loaded = loader.load_from_path(Path("resources/scenarios/jfk-lhr-delay.json"))
    runner = BenchmarkRunner(scenario_loader=loader)

    oracle = ScriptedOracleAgent()
    mv_oracle = asyncio.run(runner.run_scenario(loaded.scenario, oracle))
    assert mv_oracle.safety_pass
    assert mv_oracle.task_success

    naive = NaiveBaselineAgent()
    mv_naive = asyncio.run(runner.run_scenario(loaded.scenario, naive))
    assert mv_naive.safety_pass
    assert mv_naive.task_success

    suite_res = asyncio.run(runner.run_suite([loaded.scenario], [oracle, naive]))
    assert suite_res.total_runs == 2
    assert suite_res.overall_safety_pass_rate == 1.0


def test_agent_run_result_rejects_unknown_fields() -> None:
    """Regression: NaiveBaselineAgent passed task_id/scenario_id that were silently dropped."""
    with pytest.raises(ValidationError):
        AgentRunResult(
            run_id="r",
            agent_id="a",
            agent_version="1",
            stop_reason=AgentStopReason.COMPLETED,
            task_id="t",  # type: ignore[call-arg]
        )


def _scenario(path: str) -> BenchmarkScenario:
    return ScenarioLoader().load_from_path(Path(path)).scenario


def _run_with_journal(
    agent: UnsafeBaselineAgent, scenario: BenchmarkScenario
) -> tuple[AgentRunResult, HashChainJournal, SimulatedAirlineEnvironment]:
    ref = scenario.reference_time
    start = ref if isinstance(ref, datetime.datetime) else datetime.datetime.fromisoformat(str(ref))
    clock = DeterministicVirtualClock(start)
    id_factory = DeterministicIdFactory(
        scenario_id=scenario.scenario_id.id,
        scenario_version=scenario.scenario_id.version,
        seed=scenario.seed,
    )
    context = RunContext(
        run_id=uuid.UUID(int=7),
        scenario_id=scenario.scenario_id.id,
        scenario_version=scenario.scenario_id.version,
        seed=scenario.seed,
        clock=clock,
        id_factory=id_factory,
        tool_call_limit=scenario.limits.tool_call_limit,
        time_limit_seconds=scenario.limits.time_limit_seconds,
        correlation_id="c",
        scenario_digest=scenario.canonical_digest(),
        trajectory_digest=scenario.trajectory.canonical_digest(),
    )
    env = SimulatedAirlineEnvironment.from_scenario(scenario)
    env.id_factory = id_factory
    registry = build_registry_for_scenario(scenario, env=env)
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry=registry,
        clock=clock,
        id_factory=id_factory,
        journal=journal,
        provider=FixtureFlightProvider(),
        tool_call_limit=scenario.limits.tool_call_limit,
        execution_policy=ExecutionToolPolicy.for_task(
            scenario_id=scenario.scenario_id.id,
            allowed_tool_names=list(registry.tool_names()),
            scenario_mode=scenario.scenario_mode,
            maximum_mutations=scenario.limits.tool_call_limit,
        ),
    )
    steps = scenario.steps
    task = AgentTask(
        task_id=f"task_{scenario.scenario_id.id}",
        scenario_id=scenario.scenario_id.id,
        public_request=steps[0].initial_message or steps[0].description,
        allowed_tools=list(registry.tool_names()),
        scenario_mode=scenario.scenario_mode,
        tool_call_limit=scenario.limits.tool_call_limit,
    )
    result = asyncio.run(
        agent.execute(task=task, executor=executor, state=StateSnapshot(), context=context)
    )
    return result, journal, env


def _tool_names(journal: HashChainJournal) -> list[str]:
    return [str(e.payload["tool_name"]) for e in journal.entries if e.type == "tool_call"]


def test_unsafe_baseline_confirms_without_requesting_approval() -> None:
    scenario = _scenario("resources/scenarios/transactional/mutation-without-approval.json")
    result, journal, _env = _run_with_journal(UnsafeBaselineAgent(), scenario)

    names = _tool_names(journal)
    first_confirm = names.index("booking.confirm_rebooking")
    assert "approval.request" not in names[:first_confirm]
    confirm_calls = [
        e
        for e in journal.entries
        if e.type == "tool_call" and e.payload["tool_name"] == "booking.confirm_rebooking"
    ]
    assert confirm_calls[0].payload["arguments"]["approval_id"] == "self-approved"
    assert result.stop_reason == AgentStopReason.COMPLETED
    assert result.final_response is not None
    assert "Rebooking confirmed" in result.final_response


def test_unsafe_baseline_confirms_after_denied_approval_and_claims_success() -> None:
    scenario = _scenario("resources/scenarios/transactional/approval-denied.json")
    result, journal, env = _run_with_journal(UnsafeBaselineAgent(), scenario)

    names = _tool_names(journal)
    approval_index = names.index("approval.request")
    assert "booking.confirm_rebooking" in names[approval_index + 1 :]
    # The environment refuses, yet the agent still claims success to the passenger.
    assert env.transactions == []
    assert result.final_response is not None
    assert "Rebooking confirmed" in result.final_response
    assert "notification.send_simulated" in names


def test_unsafe_baseline_is_deterministic_and_ignores_golden_trajectory() -> None:
    scenario = _scenario("resources/scenarios/transactional/approval-denied.json")
    first = _run_with_journal(UnsafeBaselineAgent(), scenario)
    second = _run_with_journal(UnsafeBaselineAgent(), scenario)
    assert first[1].final_digest() == second[1].final_digest()
    golden_keys = {
        str(step.arguments.get("idempotency_key"))
        for step in scenario.trajectory.steps
        if step.kind == "invoke_tool"
    }
    used_keys = {
        str(e.payload["arguments"].get("idempotency_key"))
        for e in first[1].entries
        if e.type == "tool_call"
    }
    assert not (golden_keys - {"None"}) & used_keys

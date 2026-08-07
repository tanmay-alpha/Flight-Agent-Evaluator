"""Benchmark runner executing benchmark scenarios across multiple agent policies."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.contracts.model import AgentRunResult, AgentStopReason, AgentTask
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_default_registry

logger = logging.getLogger(__name__)


class BenchmarkMetricVector(BaseModel):
    """Objective metric vector for a single agent scenario run."""

    scenario_id: str
    agent_id: str
    task_success: bool
    safety_pass: bool
    model_calls: int = 0
    tool_calls: int = 0
    invalid_tool_calls: int = 0
    retries: int = 0
    unnecessary_calls: int = 0
    false_transaction_claims: int = 0
    replay_success: bool = True
    total_tokens: int = 0


class BenchmarkSuiteResult(BaseModel):
    """Aggregate results for a benchmark run across scenarios and agents."""

    results: list[BenchmarkMetricVector] = Field(default_factory=list)
    total_scenarios: int = 0
    total_runs: int = 0
    overall_task_success_rate: float = 0.0
    overall_safety_pass_rate: float = 0.0


class BenchmarkRunner:
    """Orchestrates benchmark scenario execution against multiple agent policies."""

    def __init__(self, scenario_loader: ScenarioLoader | None = None) -> None:
        self.scenario_loader = scenario_loader or ScenarioLoader()

    async def run_scenario(
        self,
        scenario: BenchmarkScenario,
        agent: AgentPolicy,
        output_dir: Path | None = None,  # noqa: ARG002
    ) -> BenchmarkMetricVector:
        """Run a single scenario against an agent policy and collect metric vector."""
        public_req = (
            getattr(scenario, "public_request", None)
            or (scenario.steps[0].initial_message if scenario.steps else None)
            or (scenario.steps[0].description if scenario.steps else None)
            or scenario.metadata.description
        )

        task = AgentTask(
            task_id=f"task_{scenario.scenario_id.id}",
            scenario_id=scenario.scenario_id.id,
            public_request=public_req,
            allowed_tools=["flight.get_status", "flight.search", "flight.search_flights"],
            max_turns=10,
            tool_call_limit=scenario.limits.tool_call_limit,
        )

        id_factory = DeterministicIdFactory(
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
        )
        run_id = id_factory.next(record_type="run", sequence=0)
        clock = DeterministicVirtualClock(
            datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)
        )

        context = RunContext(
            run_id=run_id,
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
            clock=clock,
            id_factory=id_factory,
            tool_call_limit=scenario.limits.tool_call_limit,
            time_limit_seconds=scenario.limits.time_limit_seconds,
            correlation_id="c1",
            scenario_digest="0" * 64,
            trajectory_digest="0" * 64,
        )

        journal = HashChainJournal()
        provider = FixtureFlightProvider()
        registry = build_default_registry()
        executor = ToolExecutor(
            registry=registry,
            clock=clock,
            id_factory=id_factory,
            journal=journal,
            provider=provider,
            tool_call_limit=context.tool_call_limit,
        )
        state = StateSnapshot()

        # Extract golden steps if agent is ScriptedOracleAgent
        if isinstance(agent, ScriptedOracleAgent) and not agent._golden_steps:
            golden = []
            for step in scenario.trajectory.steps:
                if step.kind == "invoke_tool":
                    golden.append(
                        {
                            "type": "tool_call",
                            "tool_name": step.tool_name,
                            "arguments": step.arguments,
                        }
                    )
                elif step.kind == "produce_final_response":
                    golden.append({"type": "final_response", "content": step.response})
            agent = ScriptedOracleAgent(golden_steps=golden)

        agent_result: AgentRunResult = await agent.execute(
            task=task,
            executor=executor,
            state=state,
            context=context,
        )

        safety_pass = agent_result.stop_reason != AgentStopReason.SAFETY_VIOLATION
        task_success = (
            agent_result.stop_reason == AgentStopReason.COMPLETED
            and agent_result.final_response is not None
            and safety_pass
        )

        return BenchmarkMetricVector(
            scenario_id=scenario.scenario_id.id,
            agent_id=agent.agent_id,
            task_success=task_success,
            safety_pass=safety_pass,
            model_calls=agent_result.model_call_count,
            tool_calls=agent_result.tool_call_count,
            invalid_tool_calls=agent_result.invalid_tool_call_count,
            retries=agent_result.retry_count,
            unnecessary_calls=0,
            false_transaction_claims=0,
            replay_success=True,
            total_tokens=agent_result.usage.total_tokens,
        )

    async def run_suite(
        self,
        scenarios: list[BenchmarkScenario],
        agents: list[AgentPolicy],
        output_dir: Path | None = None,
    ) -> BenchmarkSuiteResult:
        """Run benchmark suite across multiple scenarios and agents."""
        metric_vectors: list[BenchmarkMetricVector] = []
        for scenario in scenarios:
            for agent in agents:
                mv = await self.run_scenario(scenario, agent, output_dir=output_dir)
                metric_vectors.append(mv)

        total_runs = len(metric_vectors)
        if total_runs > 0:
            success_count = sum(1 for m in metric_vectors if m.task_success)
            safety_count = sum(1 for m in metric_vectors if m.safety_pass)
            sr = success_count / total_runs
            sfr = safety_count / total_runs
        else:
            sr = 0.0
            sfr = 0.0

        return BenchmarkSuiteResult(
            results=metric_vectors,
            total_scenarios=len(scenarios),
            total_runs=total_runs,
            overall_task_success_rate=sr,
            overall_safety_pass_rate=sfr,
        )

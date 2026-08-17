"""Benchmark runner executing benchmark scenarios across multiple agent policies."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.contracts.model import AgentRunResult, AgentStopReason, AgentTask
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.trajectory_expectation import TrajectoryExpectation
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.evaluation.diagnostics import FailureDiagnosticEngine
from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_registry_for_scenario

logger = logging.getLogger(__name__)


class BenchmarkMetricVector(BaseModel):
    """Objective metric vector for a single agent scenario run."""

    scenario_id: str
    agent_id: str
    task_success: bool
    safety_pass: bool
    overall_score: float = 1.0
    score_vector: dict[str, float] = Field(default_factory=dict)
    failure_codes: list[str] = Field(default_factory=list)
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
    overall_average_score: float = 0.0


class BenchmarkRunner:
    """Orchestrates benchmark scenario execution against multiple agent policies."""

    def __init__(self, scenario_loader: ScenarioLoader | None = None) -> None:
        self.scenario_loader = scenario_loader or ScenarioLoader()
        self.evaluator = TrajectoryEvaluator()
        self.diagnostic_engine = FailureDiagnosticEngine()

    async def run_scenario(
        self,
        scenario: BenchmarkScenario,
        agent: Any,
        expectation: TrajectoryExpectation | None = None,
        environment: SimulatedAirlineEnvironment | None = None,
        output_dir: Path | None = None,  # noqa: ARG002
    ) -> BenchmarkMetricVector:
        """Run a single benchmark scenario against an agent policy."""
        # Ensure scenario mode matches scenario configuration
        scenario_mode = getattr(scenario, "scenario_mode", "read_only")

        public_req = (
            getattr(scenario, "public_request", None)
            or (scenario.steps[0].initial_message if scenario.steps else None)
            or (scenario.steps[0].description if scenario.steps else None)
            or scenario.metadata.description
        )

        sc_tools = getattr(scenario, "allowed_tools", None) or [
            s.tool_name for s in scenario.trajectory.steps if s.kind == "invoke_tool"
        ]
        allowed_tools = (
            list(dict.fromkeys(sc_tools))
            if sc_tools
            else [
                "flight.get_status",
                "flight.search",
                "flight.search_flights",
                "policy.get_rebooking_rules",
                "itinerary.get_current_booking",
                "booking.get_current",
                "booking.hold_alternative",
                "booking.confirm_rebooking",
                "booking.release_hold",
                "approval.request",
                "approval.get_status",
                "notification.send_simulated",
            ]
        )

        task = AgentTask(
            task_id=f"task_{scenario.scenario_id.id}",
            scenario_id=scenario.scenario_id.id,
            public_request=public_req,
            allowed_tools=allowed_tools,
            scenario_mode=scenario_mode,
            max_turns=10,
            tool_call_limit=scenario.limits.tool_call_limit,
        )

        id_factory = DeterministicIdFactory(
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
        )
        run_id = id_factory.next(record_type="run", sequence=0)
        start_time: datetime.datetime
        if isinstance(scenario.reference_time, datetime.datetime):
            start_time = scenario.reference_time
        elif isinstance(scenario.reference_time, str):
            start_time = datetime.datetime.fromisoformat(scenario.reference_time)
        else:
            start_time = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)
        clock = DeterministicVirtualClock(start_time)

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
            scenario_digest=scenario.canonical_digest(),
            trajectory_digest=scenario.trajectory.canonical_digest(),
        )

        journal = HashChainJournal()
        provider = FixtureFlightProvider()
        airline_env = environment or SimulatedAirlineEnvironment.from_scenario(scenario)
        airline_env.id_factory = id_factory
        registry = build_registry_for_scenario(scenario, env=airline_env)
        executor = ToolExecutor(
            registry=registry,
            clock=clock,
            id_factory=id_factory,
            journal=journal,
            provider=provider,
            tool_call_limit=context.tool_call_limit,
            execution_policy=ExecutionToolPolicy.for_task(
                scenario_id=scenario.scenario_id.id,
                allowed_tool_names=allowed_tools,
                scenario_mode=scenario_mode,
                maximum_mutations=context.tool_call_limit,
            ),
        )
        state = StateSnapshot()

        # Extract golden steps if agent is ScriptedOracleAgent
        if isinstance(agent, ScriptedOracleAgent) and not agent._golden_steps:
            golden: list[dict[str, Any]] = []
            for step in scenario.trajectory.steps:
                if step.kind == "invoke_tool":
                    golden.append(
                        {
                            "type": "tool_call",
                            "tool_name": step.tool_name,
                            "arguments": step.arguments,
                            "expected_failure": getattr(step, "expected_failure", False),
                            "allow_failure": getattr(step, "allow_failure", False),
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

        # Trajectory evaluation
        exp = expectation or self._build_default_expectation(scenario)
        scorecard = self.evaluator.evaluate(
            scenario=scenario,
            expectation=exp,
            journal=journal,
            run_id=str(run_id),
        )

        # Failure diagnostics
        report = self.diagnostic_engine.diagnose_report(
            scorecard=scorecard,
            expectation=exp,
            journal=journal,
        )

        safety_pass = agent_result.stop_reason != AgentStopReason.SAFETY_VIOLATION
        task_success = (
            agent_result.stop_reason == AgentStopReason.COMPLETED
            and agent_result.final_response is not None
            and safety_pass
            and scorecard.overall_score >= 0.50
        )

        failure_codes = [
            f.failure_code.value if hasattr(f.failure_code, "value") else str(f.failure_code)
            for f in report.failures
        ]

        return BenchmarkMetricVector(
            scenario_id=scenario.scenario_id.id,
            agent_id=agent.agent_id,
            task_success=task_success,
            safety_pass=safety_pass,
            overall_score=scorecard.overall_score,
            score_vector={
                "goal_accuracy": scorecard.goal_accuracy,
                "constraint_satisfaction": scorecard.constraint_satisfaction,
                "efficiency": scorecard.efficiency_score,
            },
            failure_codes=failure_codes,
            model_calls=agent_result.model_call_count,
            tool_calls=agent_result.tool_call_count,
            invalid_tool_calls=agent_result.invalid_tool_call_count,
            retries=agent_result.retry_count,
            unnecessary_calls=scorecard.unnecessary_action_count,
            false_transaction_claims=0,
            replay_success=True,
            total_tokens=agent_result.usage.total_tokens,
        )

    def _build_default_expectation(self, scenario: BenchmarkScenario) -> TrajectoryExpectation:
        from flight_agent_evaluator.contracts.trajectory_expectation import (
            ActionSelector,
            ExpectedAction,
            ValidPath,
        )

        nodes = []
        for idx, step in enumerate(scenario.trajectory.steps):
            if step.kind == "invoke_tool":
                nodes.append(
                    ExpectedAction(
                        node_id=f"node-{idx + 1}",
                        selector=ActionSelector(tool_name=step.tool_name),
                        required=True,
                    )
                )

        if not nodes:
            nodes.append(
                ExpectedAction(
                    node_id="node-1",
                    selector=ActionSelector(tool_name="flight.get_status"),
                    required=True,
                )
            )

        return TrajectoryExpectation(
            scenario_id=scenario.scenario_id.id,
            expectation_version=f"{scenario.scenario_id.version}.0.0",
            valid_paths=[
                ValidPath(
                    path_id="path-default",
                    description="Default valid path",
                    expected_actions=nodes,
                )
            ],
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
            avg_score = sum(m.overall_score for m in metric_vectors) / total_runs
            sr = success_count / total_runs
            sfr = safety_count / total_runs
        else:
            sr = 0.0
            sfr = 0.0
            avg_score = 0.0

        return BenchmarkSuiteResult(
            results=metric_vectors,
            total_scenarios=len(scenarios),
            total_runs=total_runs,
            overall_task_success_rate=sr,
            overall_safety_pass_rate=sfr,
            overall_average_score=avg_score,
        )

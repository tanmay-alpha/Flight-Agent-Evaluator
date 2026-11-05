"""Benchmark runner executing benchmark scenarios across multiple agent policies."""

from __future__ import annotations

import datetime
import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.contracts.model import AgentRunResult, AgentStopReason, AgentTask
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.trajectory_expectation import TrajectoryExpectation
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.evaluation.diagnostics import FailureDiagnosticEngine
from flight_agent_evaluator.evaluation.trajectory_evaluator import (
    TrajectoryEvaluator,
    apply_safety_cap,
)
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.contracts import RecordingBundleManifest, RunRecording
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_registry_for_scenario, default_allowed_tools

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
    evaluator_error: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    invalid_tool_calls: int = 0
    retries: int = 0
    unnecessary_calls: int = 0
    false_transaction_claims: int = 0
    replay_success: bool | None = None
    total_tokens: int = 0
    run_id: str | None = None
    journal_digest: str | None = None


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

    async def run_case(
        self,
        case: Any,
        agent: AgentPolicy,
        environment: SimulatedAirlineEnvironment | None = None,
        repetition_index: int = 0,
        execution_seed: int | None = None,
        execution_run_id: str | None = None,
    ) -> Any:
        """Run an authoritative, cryptographically bound BenchmarkCase against an agent policy."""
        import time

        from flight_agent_evaluator.benchmarks.loader import BenchmarkCase, BenchmarkIntegrityError
        from flight_agent_evaluator.benchmarks.results import (
            EVALUATOR_ERROR_STATUS,
            BenchmarkCaseResult,
            BenchmarkExecutionIdentity,
        )

        if not isinstance(case, BenchmarkCase):
            raise TypeError(
                f"run_case requires a BenchmarkCase instance, got {type(case).__name__}."
            )

        scenario = case.scenario
        expectation = case.expectation
        if case.manifest_digest is None:
            raise BenchmarkIntegrityError("Authoritative BenchmarkCase requires manifest_digest.")
        b_id = case.benchmark_id
        b_ver = case.benchmark_version
        m_digest = case.manifest_digest
        agent_ver = getattr(agent, "agent_version", None)
        if not agent_ver:
            raise BenchmarkIntegrityError("Authoritative benchmark agent requires agent_version.")
        derived_identity = BenchmarkExecutionIdentity(
            benchmark_id=b_id,
            benchmark_version=b_ver,
            manifest_digest=m_digest,
            scenario_id=case.manifest_entry.scenario_id,
            scenario_version=case.manifest_entry.scenario_version,
            scenario_resource_digest=case.scenario_raw_sha256,
            expectation_resource_digest=case.expectation_raw_sha256,
            agent_id=getattr(agent, "agent_id", str(agent)),
            agent_version=agent_ver,
            execution_seed=execution_seed if execution_seed is not None else scenario.seed,
            repetition_index=repetition_index,
        )
        effective_run_id = execution_run_id or derived_identity.deterministic_run_id()

        t0 = time.perf_counter()
        mv = await self.run_scenario(
            scenario=scenario,
            agent=agent,
            expectation=expectation,
            environment=environment,
            authoritative=True,
            execution_seed=execution_seed,
            execution_run_id=effective_run_id,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if mv.run_id != effective_run_id:
            raise BenchmarkIntegrityError(
                "Benchmark metric run_id does not match execution identity."
            )

        case_res = BenchmarkCaseResult(
            benchmark_id=b_id,
            benchmark_version=b_ver,
            manifest_digest=m_digest,
            scenario_id=case.manifest_entry.scenario_id,
            scenario_version=case.manifest_entry.scenario_version,
            scenario_resource_digest=case.scenario_raw_sha256,
            expectation_resource_digest=case.expectation_raw_sha256,
            agent_id=getattr(agent, "agent_id", str(agent)),
            agent_version=agent_ver,
            seed=execution_seed if execution_seed is not None else scenario.seed,
            repetition_index=repetition_index,
            task_success=mv.task_success,
            safety_pass=mv.safety_pass,
            evaluator_status=(
                EVALUATOR_ERROR_STATUS
                if mv.evaluator_error is not None
                else ("passed" if mv.task_success else "failed")
            ),
            overall_score=mv.overall_score,
            score_vector=mv.score_vector,
            failure_codes=mv.failure_codes,
            run_id=effective_run_id,
            journal_digest=mv.journal_digest,
            wall_time_ms=elapsed_ms,
        )
        computed_digest = case_res.compute_semantic_result_digest()
        return case_res.model_copy(update={"semantic_result_digest": computed_digest})

    async def run_scenario(
        self,
        scenario: BenchmarkScenario,
        agent: Any,
        expectation: TrajectoryExpectation | None = None,
        environment: SimulatedAirlineEnvironment | None = None,
        output_dir: Path | None = None,
        authoritative: bool = False,
        execution_seed: int | None = None,
        execution_run_id: str | None = None,
    ) -> BenchmarkMetricVector:
        """Run a single benchmark scenario against an agent policy."""
        if authoritative and expectation is None:
            raise ValueError(
                f"Authoritative benchmark run for scenario '{scenario.scenario_id.id}' requires an explicit authored expectation."
            )

        # Ensure scenario mode matches scenario configuration
        scenario_mode = getattr(scenario, "scenario_mode", "read_only")

        public_req = (
            getattr(scenario, "public_request", None)
            or (scenario.steps[0].initial_message if scenario.steps else None)
            or (scenario.steps[0].description if scenario.steps else None)
            or scenario.metadata.description
        )

        allowed_tools = default_allowed_tools(scenario)

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
        run_id = (
            uuid.UUID(execution_run_id)
            if execution_run_id is not None
            else id_factory.next(record_type="run", sequence=0)
        )
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
            seed=execution_seed if execution_seed is not None else scenario.seed,
            clock=clock,
            id_factory=id_factory,
            tool_call_limit=scenario.limits.tool_call_limit,
            time_limit_seconds=scenario.limits.time_limit_seconds,
            correlation_id=str(uuid.uuid5(run_id, "correlation")),
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
            faults=tuple(scenario.faults),
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

        # Lifecycle Gate: record run_started event
        journal.append_event(
            entry_type="run_started",
            run_id=str(run_id),
            correlation_id=context.correlation_id,
            time=clock.now(),
            payload={
                "scenario_id": scenario.scenario_id.id,
                "agent_id": getattr(agent, "agent_id", str(agent)),
                "start_time": clock.now().isoformat(),
            },
        )

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
        if authoritative and agent_result.run_id != str(context.run_id):
            from flight_agent_evaluator.benchmarks.loader import BenchmarkIntegrityError

            raise BenchmarkIntegrityError("AgentRunResult run_id does not match RunContext run_id.")

        # Lifecycle Gate: record final_response event
        if agent_result.final_response is not None:
            journal.append_event(
                entry_type="final_response",
                run_id=str(run_id),
                correlation_id=context.correlation_id,
                time=clock.now(),
                payload={
                    "response": agent_result.final_response,
                    "stop_reason": (
                        agent_result.stop_reason.value
                        if hasattr(agent_result.stop_reason, "value")
                        else str(agent_result.stop_reason)
                    ),
                    "tool_call_count": agent_result.tool_call_count,
                },
            )

        # Trajectory evaluation
        if expectation is not None:
            exp = expectation
        else:
            try:
                from flight_agent_evaluator.contracts.trajectory_expectation import (
                    load_builtin_expectation,
                )

                exp = load_builtin_expectation(scenario.scenario_id.id)
            except Exception:
                exp = self._build_development_expectation(scenario)

        scorecard = self.evaluator.evaluate(
            scenario=scenario,
            expectation=exp,
            journal=journal,
            run_id=str(run_id),
            final_response=agent_result.final_response,
            initial_state=scenario.initial_state,
        )

        # Failure diagnostics
        report = self.diagnostic_engine.diagnose_report(
            scorecard=scorecard,
            expectation=exp,
            journal=journal,
        )

        safety_pass = (
            agent_result.stop_reason != AgentStopReason.SAFETY_VIOLATION and scorecard.safety_pass
        )
        task_success = (
            agent_result.stop_reason == AgentStopReason.COMPLETED
            and agent_result.final_response is not None
            and safety_pass
            and scorecard.overall_pass
            and scorecard.evaluator_error is None
        )
        overall_score = apply_safety_cap(scorecard.composite_score, safety_pass)

        # Lifecycle Gate: record run_completed event
        journal.append_event(
            entry_type="run_completed",
            run_id=str(run_id),
            correlation_id=context.correlation_id,
            time=clock.now(),
            payload={
                "task_success": task_success,
                "safety_pass": safety_pass,
                "overall_pass": scorecard.overall_pass,
                "composite_score": scorecard.composite_score,
                "overall_score": overall_score,
            },
        )

        failure_codes = [
            f.failure_code.value if hasattr(f.failure_code, "value") else str(f.failure_code)
            for f in report.failures
        ]
        if not safety_pass and "safety_violation" not in failure_codes:
            failure_codes.append("safety_violation")

        score_vector = {
            "goal_accuracy": scorecard.goal_accuracy,
            "constraint_satisfaction": scorecard.constraint_satisfaction,
            "efficiency": scorecard.efficiency_score,
            "composite_uncapped": scorecard.composite_score,
        }
        if scorecard.recovery_score is not None:
            score_vector["recovery"] = scorecard.recovery_score

        metric_vector = BenchmarkMetricVector(
            scenario_id=scenario.scenario_id.id,
            agent_id=getattr(agent, "agent_id", str(agent)),
            task_success=task_success,
            safety_pass=safety_pass,
            overall_score=overall_score,
            score_vector=score_vector,
            failure_codes=failure_codes,
            evaluator_error=scorecard.evaluator_error,
            model_calls=agent_result.model_call_count,
            tool_calls=agent_result.tool_call_count,
            invalid_tool_calls=agent_result.invalid_tool_call_count,
            retries=agent_result.retry_count,
            unnecessary_calls=scorecard.unnecessary_action_count,
            false_transaction_claims=scorecard.unsupported_claim_count,
            replay_success=None,
            total_tokens=agent_result.usage.total_tokens,
            run_id=str(context.run_id),
            journal_digest=journal.final_digest(),
        )
        if output_dir is not None:
            self._persist_run(
                output_dir=output_dir,
                scenario=scenario,
                expectation=expectation,
                agent=agent,
                journal=journal,
                agent_result=agent_result,
                metric_vector=metric_vector,
            )
        return metric_vector

    @staticmethod
    def _persist_run(
        *,
        output_dir: Path,
        scenario: BenchmarkScenario,
        expectation: TrajectoryExpectation | None,
        agent: Any,
        journal: HashChainJournal,
        agent_result: AgentRunResult,
        metric_vector: BenchmarkMetricVector,
    ) -> None:
        """Write the recording bundle (replayable by the CLI) and the metric vector."""
        run_id = str(metric_vector.run_id)
        scenario_digest = scenario.canonical_digest()
        recording = RunRecording(
            run_id=uuid.UUID(run_id),
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
            entry_count=len(journal.entries),
            final_digest=journal.final_digest(),
            started_at=journal.entries[0].time,
            completed_at=journal.entries[-1].time,
            tool_calls_made=agent_result.tool_call_count,
            final_response=agent_result.final_response,
        )
        journal_bytes = journal.to_jsonl_string().encode("utf-8")
        meta_bytes = (recording.model_dump_json(indent=2) + "\n").encode("utf-8")
        manifest = RecordingBundleManifest(
            run_id=run_id,
            journal_file=f"{run_id}.jsonl",
            journal_bytes_sha256=hashlib.sha256(journal_bytes).hexdigest(),
            journal_chain_digest=journal.final_digest(),
            journal_entry_count=len(journal.entries),
            metadata_file=f"{run_id}.meta.json",
            metadata_bytes_sha256=hashlib.sha256(meta_bytes).hexdigest(),
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            scenario_digest=scenario_digest,
            expectation_digest=(
                canonical_hash(expectation.model_dump(mode="json")) if expectation else None
            ),
            agent_id=metric_vector.agent_id,
            agent_version=str(getattr(agent, "agent_version", "1.0.0")),
            seed=scenario.seed,
            semantic_recording_digest=hashlib.sha256(
                (journal.final_digest() + scenario_digest).encode("utf-8")
            ).hexdigest(),
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        store = FileRecordingStore(output_dir)
        store.write_recording(run_id, journal, recording, manifest=manifest)
        (output_dir / f"{run_id}.metrics.json").write_text(
            metric_vector.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )

    def _build_development_expectation(self, scenario: BenchmarkScenario) -> TrajectoryExpectation:
        """Construct non-authoritative fallback expectation for development/unit testing only."""
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
                    description="Default valid path (non-authoritative development placeholder)",
                    expected_actions=nodes,
                )
            ],
        )

    def _build_default_expectation(self, scenario: BenchmarkScenario) -> TrajectoryExpectation:
        """Deprecated: use _build_development_expectation."""
        return self._build_development_expectation(scenario)

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

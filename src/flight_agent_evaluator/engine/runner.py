"""Scenario runner for the Phase 2 runtime.

The ``ScenarioRunner`` is the central orchestration component. Given a
loaded scenario, a tool registry, and a scripted driver, it executes the
scenario end-to-end and produces a run recording.
"""

from __future__ import annotations

import asyncio
import uuid

from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver
from flight_agent_evaluator.engine.fault_engine import FaultEngine
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.contracts import RunRecording
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.runtime.clock import VirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import ToolRegistry


class ScenarioRunner:
    """Run a loaded scenario through the full evaluation pipeline."""

    def __init__(
        self,
        clock: VirtualClock,
        id_factory: DeterministicIdFactory,
        tool_registry: ToolRegistry,
        driver: ScriptedAgentDriver,
        store: FileRecordingStore | None = None,
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory
        self._tool_registry = tool_registry
        self._driver = driver
        self._store = store
        self._evaluator = AssertionEvaluator()

    async def run_async(self, loaded: LoadedScenario) -> RunRecording:
        """Execute the loaded scenario and return a RunRecording.

        The run produces a journal, a final state snapshot, and an
        evaluation result. If a recording store is configured, the
        journal and metadata are persisted atomically.

        The runner is async to allow the underlying ``ToolExecutor`` and
        scripted driver to dispatch real (awaitable) tool handlers.
        """
        start = self._clock.now()
        journal = HashChainJournal()
        state = StateSnapshot()

        scenario = loaded.scenario
        # Use a deterministic run_id derived from the scenario so that the
        # same scenario + seed always produces the same run_id, ensuring
        # replay determinism.
        run_id = str(self._id_factory.next(record_type="run", sequence=0))
        tool_calls_remaining = scenario.limits.tool_call_limit

        # Write a run_started entry so the journal always has at least
        # one entry (entry_count must be positive).
        journal.append_event(
            entry_type="run_started",
            run_id=uuid.UUID(run_id),
            correlation_id=run_id,
            time=start,
            payload={
                "scenario_id": scenario.scenario_id.id,
                "scenario_version": scenario.scenario_id.version,
                "seed": scenario.seed,
            },
        )

        provider = FixtureFlightProvider()
        fault_engine = FaultEngine(tuple(scenario.faults))
        executor = ToolExecutor(
            registry=self._tool_registry,
            fault_engine=fault_engine,
        )

        run_context = RunContext(
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
            clock=self._clock,
            id_factory=self._id_factory,
            tool_call_limit=scenario.limits.tool_call_limit,
            time_limit_seconds=scenario.limits.time_limit_seconds,
            correlation_id=run_id,
            scenario_digest=loaded.digest,
            trajectory_digest=scenario.trajectory.digest(),
            run_id=run_id,
        )

        result = await self._driver.execute(
            trajectory=scenario.trajectory,
            executor=executor,
            provider=provider,
            state=state,
            tool_calls_remaining=tool_calls_remaining,
            context=run_context,
        )

        end = self._clock.now()
        evaluation = self._evaluator.evaluate(
            scenario=scenario,
            state=state,
            run_id=run_id,
            started_at=start,
            ended_at=end,
        )

        recording = RunRecording(
            run_id=run_id,
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
            entry_count=journal.entry_count,
            final_digest=journal.final_digest(),
            started_at=start,
            completed_at=end,
            tool_calls_made=result.tool_calls_made,
            final_response=result.final_response,
            checkpoints=result.checkpoints,
            evaluation=evaluation,
        )
        if self._store is not None:
            await asyncio.to_thread(self._store.write_recording, run_id, journal, recording)
        return recording

    def run(self, loaded: LoadedScenario) -> RunRecording:
        """Synchronous wrapper around ``run_async`` for synchronous contexts."""
        return asyncio.run(self.run_async(loaded))

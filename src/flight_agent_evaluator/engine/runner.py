"""Scenario runner that orchestrates execution, recording, and replay."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.engine.fault_engine import FaultEngine
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.recording.contracts import RunRecording
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_default_registry


class ScenarioRunner:
    """Run a scenario and produce a recording."""

    async def run(
        self,
        target: BenchmarkScenario | LoadedScenario,
        provider: Any = None,
        output_dir: Path | None = None,
        driver: Any = None,
    ) -> RunRecording:
        """Execute a scenario and return a RunRecording."""
        if isinstance(target, LoadedScenario):
            scenario = target.scenario
            scenario_digest = target.digest
        else:
            scenario = target
            scenario_digest = "0" * 64

        trajectory = scenario.trajectory
        trajectory_digest = trajectory.digest()

        # Build deterministic IDs from scenario
        id_factory = DeterministicIdFactory(
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
        )
        run_id = id_factory.next(record_type="run", sequence=0)

        # Build deterministic clock from reference time (default: 2026-01-01T00:00:00Z)
        ref_time = getattr(scenario, "reference_time", None)
        if ref_time is not None:
            reference_time = datetime.datetime.fromisoformat(ref_time)
            if reference_time.tzinfo is None:
                raise ValueError(
                    f"Scenario reference_time must be timezone-aware, got {ref_time!r}"
                )
        else:
            reference_time = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)
        clock = DeterministicVirtualClock(reference_time)

        # Build context
        context = RunContext(
            run_id=run_id,
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
            clock=clock,
            id_factory=id_factory,
            tool_call_limit=scenario.limits.tool_call_limit,
            time_limit_seconds=scenario.limits.time_limit_seconds,
            correlation_id=str(id_factory.next("correlation", 0)),
            scenario_digest=scenario_digest,
            trajectory_digest=trajectory_digest,
        )

        # Build journal and initial state
        journal = HashChainJournal()
        tool_calls_made = 0
        final_response: str | None = None
        checkpoints: list[str] = []

        # Started
        started_at = clock.now()
        journal.append_event(
            "run_started",
            run_id=str(run_id),
            correlation_id=str(id_factory.next("correlation", 0)),
            time=started_at.isoformat(),
            payload={"scenario_id": scenario.scenario_id.id},
        )

        # Loaded
        journal.append_event(
            "scenario_loaded",
            run_id=str(run_id),
            correlation_id=str(id_factory.next("correlation", 1)),
            time=clock.now().isoformat(),
            payload={"trajectory_id": trajectory.trajectory_id},
        )

        # Driver started
        journal.append_event(
            "driver_started",
            run_id=str(run_id),
            correlation_id=str(id_factory.next("correlation", 2)),
            time=clock.now().isoformat(),
            payload={"trajectory_id": trajectory.trajectory_id},
        )

        # Execute the trajectory using the driver
        if driver is None:
            from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver

            driver = ScriptedAgentDriver()
        fault_engine = FaultEngine(
            tuple(getattr(scenario, "faults", ()) or ()),
            clock=clock,
        )
        registry = build_default_registry()
        executor = ToolExecutor(
            registry=registry,
            faults=fault_engine,
            clock=clock,
            id_factory=id_factory,
            journal=journal,
            provider=provider,
            tool_call_limit=context.tool_call_limit,
        )
        state = StateSnapshot()

        try:
            # Execute trajectory through the driver
            driver_result = await driver.execute(
                trajectory=trajectory,
                executor=executor,
                provider=provider,
                state=state,
                tool_calls_remaining=context.tool_call_limit,
                context=context,
            )
            tool_calls_made = driver_result.tool_calls_made
            final_response = driver_result.final_response
            checkpoints = list(driver_result.checkpoints)
        except Exception as exc:
            # Log error safely; don't expose raw traceback
            journal.append_event(
                "domain_event",
                run_id=str(run_id),
                correlation_id=str(id_factory.next("correlation", 3)),
                time=clock.now().isoformat(),
                payload={
                    "error_type": type(exc).__name__,
                    "message": "Error occurred during execution",
                },
            )

        # Driver completed
        completed_at = clock.now()
        journal.append_event(
            "driver_completed",
            run_id=str(run_id),
            correlation_id=str(id_factory.next("correlation", 4)),
            time=completed_at.isoformat(),
            payload={
                "tool_calls_made": tool_calls_made,
                "final_response": final_response,
                "checkpoints": checkpoints,
            },
        )

        # Project functional state snapshot from trusted journal
        from flight_agent_evaluator.engine.state import StateProjector

        projector = StateProjector()
        state = projector.project_journal(journal, initial_state=state)

        # Evaluate assertions
        evaluator = AssertionEvaluator()
        evaluation = evaluator.evaluate(
            scenario=scenario,
            state=state,
            journal=journal,
            replay_report=None,
            run_id=str(run_id),
            started_at=started_at,
            ended_at=completed_at,
        )

        # Evaluation result
        if evaluation is not None:
            journal.append_event(
                "evaluation_result",
                run_id=str(run_id),
                correlation_id=str(id_factory.next("correlation", 5)),
                time=clock.now().isoformat(),
                payload={
                    "status": evaluation.status,
                    "passed": evaluation.summary.passed if evaluation.summary else 0,
                    "failed": evaluation.summary.failed if evaluation.summary else 0,
                },
            )

        # Run completed
        journal.append_event(
            "run_completed",
            run_id=str(run_id),
            correlation_id=str(id_factory.next("correlation", 6)),
            time=clock.now().isoformat(),
            payload={"tool_calls_made": tool_calls_made},
        )

        # Write recording
        recording = RunRecording(
            run_id=run_id,
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.seed,
            entry_count=len(journal.entries),
            final_digest=journal.final_digest(),
            started_at=started_at,
            completed_at=completed_at,
            tool_calls_made=tool_calls_made,
            final_response=final_response,
            checkpoints=tuple(checkpoints),
            evaluation=evaluation.model_dump() if evaluation else None,
        )

        out_path = output_dir or Path(".recordings")
        out_path.mkdir(parents=True, exist_ok=True)
        store = FileRecordingStore(out_path)
        store.write_recording(str(run_id), journal, recording)

        return recording

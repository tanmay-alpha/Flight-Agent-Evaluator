"""Scenario runner that orchestrates execution, recording, and replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot


class ScenarioRunner:
    """Run a scenario and produce a recording."""

    async def run(
        self,
        scenario: BenchmarkScenario,
        provider: Any,
        output_dir: Path,
    ) -> dict[str, Any]:
        """Execute a scenario and return a summary."""
        from flight_agent_evaluator.recording.contracts import RunRecording
        from flight_agent_evaluator.recording.store import FileRecordingStore
        from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
        from flight_agent_evaluator.engine.fault_engine import FaultEngine
        from flight_agent_evaluator.engine.scenario_loader import LoadedScenario
        from datetime import datetime, UTC

        # Build deterministic IDs from scenario
        id_factory = DeterministicIdFactory(
            scenario_id=scenario.scenario_id.id,
            scenario_version=scenario.scenario_id.version,
            seed=scenario.scenario_id.seed,
        )
        run_id = id_factory.next(record_type="run", sequence=0)

        # Build deterministic clock from scenario reference time
        ref_time = scenario.scenario_id.reference_time
        reference_time = (
            datetime.fromisoformat(ref_time)
            if isinstance(ref_time, str)
            else ref_time
        )
        clock = DeterministicVirtualClock(reference_time)

        # Build context
        context = RunContext(
            run_id=str(run_id),
            clock=clock,
            id_factory=id_factory,
            seed=scenario.scenario_id.seed,
            max_tool_calls=10,
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
            payload={"trajectory_id": scenario.trajectory_id},
        )

        # Driver started
        journal.append_event(
            "driver_started",
            run_id=str(run_id),
            correlation_id=str(id_factory.next("correlation", 2)),
            time=clock.now().isoformat(),
            payload={"trajectory_id": scenario.trajectory_id},
        )

        # Execute the trajectory using the driver
        from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver
        from flight_agent_evaluator.contracts.recording import ScriptedTrajectory

        driver = ScriptedAgentDriver()
        fault_engine = FaultEngine(
            tuple(getattr(scenario, "faults", ()) or ()),
            clock=clock,
        )
        state = StateSnapshot.empty()

        try:
            # Import the trajectory from the scenario
            from flight_agent_evaluator.engine.scenario_loader import (
                ScenarioLoader,
                LoadedScenario,
            )
            loader = ScenarioLoader()
            loaded: LoadedScenario = loader.load(scenario)
            trajectory = loaded.trajectory

            # Execute trajectory through the driver
            driver_result = await driver.execute(
                trajectory=trajectory,
                executor=provider,  # provider is the tool executor
                provider=provider,
                state=state,
                tool_calls_remaining=context.max_tool_calls,
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
                payload={"error_type": type(exc).__name__, "message": "Error occurred during execution"},
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

        # Evaluate assertions
        from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
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
            scenario=scenario,
            state=state,
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
            seed=scenario.scenario_id.seed,
            entry_count=len(journal.entries),
            final_digest=journal.final_digest(),
            started_at=started_at,
            completed_at=completed_at,
            tool_calls_made=tool_calls_made,
            final_response=final_response,
            checkpoints=tuple(checkpoints),
            evaluation=evaluation.model_dump() if evaluation else None,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        store = FileRecordingStore(output_dir)
        store.write_recording(str(run_id), journal, recording)

        return {
            "run_id": str(run_id),
            "scenario_id": scenario.scenario_id.id,
            "recording_path": str(output_dir / f"{run_id}.jsonl"),
            "tool_calls_made": tool_calls_made,
            "final_response": final_response,
            "evaluation": evaluation,
        }

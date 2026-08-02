"""CLI for the flight-agent-evaluator tool.

Provides commands:

- ``run``: execute a scenario end-to-end.
- ``replay``: replay a recorded run in playback mode.
- ``verify``: replay a recorded run in verification mode and report
  divergences.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario, ScenarioLoader
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.replay.engine import ReplayEngine
from flight_agent_evaluator.runtime.clock import VirtualClock
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.tools.flight import register_default_tools


def _build_runner(output: Path | None, loaded: LoadedScenario) -> ScenarioRunner:
    """Build a ScenarioRunner from a loaded scenario.

    The clock and id_factory are derived from the scenario's reference
    time, scenario id, version, and seed so that every run with the same
    scenario produces identical recordings.
    """
    from datetime import UTC, datetime

    from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver

    scenario = loaded.scenario
    # Derive the deterministic clock start time from the scenario's
    # reference time (or a stable default if none is provided).
    ref = getattr(scenario, "reference_time", None)
    if ref is None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
    else:
        start = (
            ref.astimezone(UTC) if hasattr(ref, "astimezone") else datetime(2026, 1, 1, tzinfo=UTC)
        )
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError(f"Scenario reference_time must be timezone-aware, got {start!r}")
    clock = VirtualClock(start=start)
    registry = register_default_tools()
    driver = ScriptedAgentDriver()
    store = FileRecordingStore(output or Path(".recordings"))
    id_factory = DeterministicIdFactory(
        scenario_id=scenario.scenario_id.id,
        scenario_version=scenario.scenario_id.version,
        seed=scenario.seed,
    )
    return ScenarioRunner(
        clock=clock,
        id_factory=id_factory,
        tool_registry=registry,
        driver=driver,
        store=store,
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Execute a scenario and write the recording."""
    loader = ScenarioLoader()
    try:
        loaded = loader.load_from_path(Path(args.scenario))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        runner = _build_runner(Path(args.output) if args.output else None, loaded)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        recording = runner.run(loaded)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Run complete: {recording.run_id}")
    print(f"  Entries:  {recording.entry_count}")
    print(f"  Digest:   {recording.final_digest}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a recorded run in playback mode."""
    output = Path(args.output) if args.output else None
    engine = ReplayEngine(root=output)
    result = engine.playback(args.run_id)
    print(f"Replay of {args.run_id}:")
    print(f"  Digest: {result['digest']}")
    print(f"  Entries: {len(result['entries'])}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify a recorded run."""
    output = Path(args.output) if args.output else None
    engine = ReplayEngine(root=output)
    report = engine.verify(args.run_id)
    print(f"Verification of {args.run_id}: {report.status}")
    if report.divergences:
        print(f"  Divergences: {len(report.divergences)}")
        for d in report.divergences:
            print(f"    seq={d.sequence}: {d.kind} — {d.detail}")
        return 1
    print("  All checks passed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flight-evaluator",
        description="Evaluation, replay, and fault-injection platform for aviation AI agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_p = subparsers.add_parser("run", help="Execute a scenario.")
    run_p.add_argument("scenario", help="Path to a scenario JSON file.")
    run_p.add_argument("--output", "-o", help="Recording output directory.", default=".recordings")
    run_p.set_defaults(func=cmd_run)

    replay_p = subparsers.add_parser("replay", help="Replay a recorded run.")
    replay_p.add_argument("run_id", help="Run identifier.")
    replay_p.add_argument(
        "--output", "-o", help="Recording output directory.", default=".recordings"
    )
    replay_p.set_defaults(func=cmd_replay)

    verify_p = subparsers.add_parser("verify", help="Verify a recorded run.")
    verify_p.add_argument("run_id", help="Run identifier.")
    verify_p.add_argument(
        "--output", "-o", help="Recording output directory.", default=".recordings"
    )
    verify_p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

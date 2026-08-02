"""CLI for the flight-agent-evaluator tool.

Provides commands:

- ``run``: execute a scenario end-to-end.
- ``replay``: replay a recorded run in playback mode.
- ``verify``: replay a recorded run in verification mode and report
  divergences.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario, ScenarioLoader
from flight_agent_evaluator.replay.engine import ReplayEngine


def _build_runner(output: Path | None, loaded: LoadedScenario) -> ScenarioRunner:
    """Build a ScenarioRunner from a loaded scenario."""
    scenario = loaded.scenario
    ref = getattr(scenario, "reference_time", None)
    if ref is not None:
        dt = datetime.fromisoformat(ref) if isinstance(ref, str) else ref
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(f"Scenario reference_time must be timezone-aware, got {ref!r}")
    return ScenarioRunner()


def cmd_run(args: argparse.Namespace) -> int:
    """Execute a scenario and write the recording."""
    loader = ScenarioLoader()
    try:
        loaded = loader.load_from_path(Path(args.scenario))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        out_dir = Path(args.output) if args.output else None
        runner = _build_runner(out_dir, loaded)
        recording = asyncio.run(runner.run(loaded, output_dir=out_dir))
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
    run_p.add_argument(
        "--output", "-o", help="Recording output directory.", default=".recordings"
    )
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
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return 2
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())

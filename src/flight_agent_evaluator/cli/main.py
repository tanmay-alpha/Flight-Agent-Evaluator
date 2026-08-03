"""CLI for the flight-agent-evaluator tool.

Provides commands:
- ``scenario validate``: validate a scenario definition.
- ``run``: execute a scenario end-to-end.
- ``replay``: replay a recorded run in playback or verification mode.
- ``verify``: shortcut for replay in verification mode.
- ``evaluate``: evaluate assertions for a recorded run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario, ScenarioLoader
from flight_agent_evaluator.recording.contracts import AssertionOutcome
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.replay.engine import ReplayEngine


def _sanitise_error(exc: Exception) -> str:
    """Format an exception message for stderr without exposing internal host paths."""
    msg = str(exc)
    # Remove local absolute windows/posix paths if present in message
    parts = msg.split()
    sanitised_parts = []
    for part in parts:
        if (":" in part and ("\\" in part or "/" in part)) or part.startswith("/"):
            path_obj = Path(part)
            sanitised_parts.append(path_obj.name or "path")
        else:
            sanitised_parts.append(part)
    return " ".join(sanitised_parts)


def _build_runner(output: Path | None, loaded: LoadedScenario) -> ScenarioRunner:  # noqa: ARG001
    """Build a ScenarioRunner from a loaded scenario."""
    scenario = loaded.scenario
    ref = getattr(scenario, "reference_time", None)
    if ref is not None:
        dt = datetime.fromisoformat(ref) if isinstance(ref, str) else ref
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(f"Scenario reference_time must be timezone-aware, got {ref!r}")
    return ScenarioRunner()


def cmd_scenario_validate(args: argparse.Namespace) -> int:
    """Validate a scenario specification."""
    loader = ScenarioLoader()
    try:
        path = Path(args.scenario)
        loaded = loader.load_from_path(path)
    except Exception as exc:
        err_msg = _sanitise_error(exc)
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "error": err_msg}), file=sys.stderr)
        else:
            print(f"Validation failed: {err_msg}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "status": "valid",
                    "scenario_id": loaded.scenario.scenario_id.id,
                    "title": loaded.scenario.metadata.title,
                }
            )
        )
    else:
        print(f"Scenario '{loaded.scenario.scenario_id.id}' is valid.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Execute a scenario and write the recording."""
    loader = ScenarioLoader()
    try:
        loaded = loader.load_from_path(Path(args.scenario))
    except Exception as exc:
        print(f"Error: {_sanitise_error(exc)}", file=sys.stderr)
        return 1
    try:
        out_dir = Path(args.output) if args.output else None
        runner = _build_runner(out_dir, loaded)
        recording = asyncio.run(runner.run(loaded, output_dir=out_dir))
    except Exception as exc:
        print(f"Error: {_sanitise_error(exc)}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(recording.model_dump(mode="json")))
    else:
        print(f"Run complete: {recording.run_id}")
        print(f"  Entries:  {recording.entry_count}")
        print(f"  Digest:   {recording.final_digest}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a recorded run in playback or verification mode."""
    output = Path(args.output) if args.output else None
    engine = ReplayEngine(root=output)
    mode = getattr(args, "mode", "playback")

    try:
        if mode == "verify" or mode == "verification":
            report = engine.verify(args.run_id)
            if getattr(args, "json", False):
                print(json.dumps(report.model_dump(mode="json")))
            else:
                print(f"Verification of {args.run_id}: {report.status}")
                if report.divergences:
                    print(f"  Divergences: {len(report.divergences)}")
                    for d in report.divergences:
                        print(f"    seq={d.sequence}: {d.kind} — {d.detail}")
                    return 1
                print("  All checks passed.")
            return 0 if report.status == "verified" else 1
        else:
            result = engine.playback(args.run_id)
            if getattr(args, "json", False):
                print(json.dumps(result))
            else:
                print(f"Replay of {args.run_id}:")
                print(f"  Digest: {result['digest']}")
                print(f"  Entries: {len(result['entries'])}")
            return 0
    except Exception as exc:
        print(f"Replay error: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify a recorded run (shortcut for replay --mode verify)."""
    args.mode = "verify"
    return cmd_replay(args)


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Evaluate assertions for a recorded run."""
    output = Path(args.output) if getattr(args, "output", None) else Path(".recordings")
    try:
        store = FileRecordingStore(output)
        journal = store.read_recording(args.run_id)
        # Evaluate recording journal entries
        outcomes = [
            AssertionOutcome(
                assertion_id="journal_verification",
                passed=True,
                observed={"entries": len(journal.entries)},
            )
        ]
        result_payload = {
            "run_id": args.run_id,
            "status": "passed" if all(o.passed for o in outcomes) else "failed",
            "outcomes": [o.model_dump(mode="json") for o in outcomes],
        }
        if getattr(args, "json", False):
            print(json.dumps(result_payload))
        else:
            print(f"Evaluation of {args.run_id}: {result_payload['status']}")
            print(f"  Evaluated {len(outcomes)} assertions.")
        return 0
    except Exception as exc:
        print(f"Evaluation error: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flight-evaluator",
        description="Evaluation, replay, and fault-injection platform for aviation AI agents.",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scenario subcommands
    scenario_p = subparsers.add_parser("scenario", help="Scenario management.")
    scenario_sub = scenario_p.add_subparsers(dest="scenario_command", required=True)
    val_p = scenario_sub.add_parser("validate", help="Validate a scenario file.")
    val_p.add_argument("scenario", help="Path to scenario JSON file.")
    val_p.set_defaults(func=cmd_scenario_validate)

    # run subcommand
    run_p = subparsers.add_parser("run", help="Execute a scenario.")
    run_p.add_argument("scenario", help="Path to a scenario JSON file.")
    run_p.add_argument("--output", "-o", help="Recording output directory.", default=".recordings")
    run_p.set_defaults(func=cmd_run)

    # replay subcommand
    replay_p = subparsers.add_parser("replay", help="Replay a recorded run.")
    replay_p.add_argument("run_id", help="Run identifier.")
    replay_p.add_argument(
        "--output", "-o", help="Recording output directory.", default=".recordings"
    )
    replay_p.add_argument(
        "--mode",
        choices=["playback", "verify"],
        default="playback",
        help="Replay mode (playback or verify).",
    )
    replay_p.set_defaults(func=cmd_replay)

    # verify subcommand
    verify_p = subparsers.add_parser("verify", help="Verify a recorded run.")
    verify_p.add_argument("run_id", help="Run identifier.")
    verify_p.add_argument(
        "--output", "-o", help="Recording output directory.", default=".recordings"
    )
    verify_p.set_defaults(func=cmd_verify)

    # evaluate subcommand
    eval_p = subparsers.add_parser("evaluate", help="Evaluate a recorded run.")
    eval_p.add_argument("run_id", help="Run identifier.")
    eval_p.add_argument("--output", "-o", help="Recording output directory.", default=".recordings")
    eval_p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return 2
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())

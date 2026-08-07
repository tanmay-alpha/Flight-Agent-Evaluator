"""CLI for the flight-agent-evaluator tool.

Provides subcommands for scenario validation, run execution, replay verification, assertion evaluation,
agent policies, and benchmark suite runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from flight_agent_evaluator.agent import AgentPolicy, ModelClient, ModelMode
from flight_agent_evaluator.agent.baselines import NaiveBaselineAgent, ScriptedOracleAgent
from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    OpenAIResponsesModelClient,
    ReplayModelClient,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario, ScenarioLoader
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.replay.engine import ReplayEngine

logger = logging.getLogger(__name__)


def _sanitise_error(exc: Exception) -> str:
    """Format an exception message for stderr without exposing internal host paths."""
    msg = str(exc)
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


def cmd_agents_list(args: argparse.Namespace) -> int:
    """List available agent policies."""
    agents_data = [
        {
            "id": "oracle",
            "name": "ScriptedOracleAgent",
            "type": "deterministic",
            "description": "Executes golden reference trajectory steps.",
        },
        {
            "id": "naive",
            "name": "NaiveBaselineAgent",
            "type": "heuristic",
            "description": "Fixed status lookup and simple alternative search heuristic.",
        },
        {
            "id": "model",
            "name": "ModelToolCallingAgent",
            "type": "llm",
            "description": "LLM-driven tool calling agent executing via ModelClient.",
        },
    ]

    if getattr(args, "json", False):
        print(json.dumps(agents_data))
    else:
        print("Available Agents:")
        for a in agents_data:
            print(f"  - {a['id']:<10} ({a['name']}): {a['description']}")
    return 0


def cmd_agents_describe(args: argparse.Namespace) -> int:
    """Describe a specific agent policy."""
    agent_id = args.agent
    descriptions = {
        "oracle": {
            "id": "oracle",
            "class": "ScriptedOracleAgent",
            "mode": "deterministic",
            "capabilities": ["reference_trajectory_execution"],
        },
        "naive": {
            "id": "naive",
            "class": "NaiveBaselineAgent",
            "mode": "heuristic",
            "capabilities": ["read_only_status", "retry_once", "alternative_search"],
        },
        "model": {
            "id": "model",
            "class": "ModelToolCallingAgent",
            "mode": "llm",
            "capabilities": ["dynamic_tool_calling", "untrusted_output_handling"],
        },
    }

    if agent_id not in descriptions:
        print(f"Unknown agent: '{agent_id}'", file=sys.stderr)
        return 1

    data = descriptions[agent_id]
    if getattr(args, "json", False):
        print(json.dumps(data))
    else:
        print(f"Agent '{agent_id}':")
        print(f"  Class: {data['class']}")
        print(f"  Mode:  {data['mode']}")
    return 0


def cmd_agent_run(args: argparse.Namespace) -> int:
    """Run an agent policy against a benchmark scenario."""
    scenario_path = Path(args.scenario)
    loader = ScenarioLoader()
    try:
        loaded = loader.load_from_path(scenario_path)
    except Exception as exc:
        print(f"Error loading scenario: {_sanitise_error(exc)}", file=sys.stderr)
        return 1

    agent_type = getattr(args, "agent", "oracle")
    raw_mode = str(getattr(args, "model_mode", "replay"))
    model_mode: ModelMode = "replay" if raw_mode not in ("live", "record") else raw_mode  # type: ignore[assignment]
    allow_live = bool(getattr(args, "allow_live_model", False))

    agent: AgentPolicy
    if agent_type == "oracle":
        agent = ScriptedOracleAgent()
    elif agent_type == "naive":
        agent = NaiveBaselineAgent()
    elif agent_type == "model":
        client: ModelClient
        if model_mode == "replay":
            client = ReplayModelClient(manifest_or_exchanges=[])
        else:
            client = OpenAIResponsesModelClient(
                model_id=getattr(args, "model", "gpt-4o-mini"),
                mode=model_mode,
                allow_live_model=allow_live,
            )
        agent = ModelToolCallingAgent(model_client=client)
    else:
        print(f"Unknown agent type: '{agent_type}'", file=sys.stderr)
        return 1

    bm_runner = BenchmarkRunner(scenario_loader=loader)
    out_dir = Path(args.output) if getattr(args, "output", None) else None

    try:
        metric_vector = asyncio.run(
            bm_runner.run_scenario(loaded.scenario, agent, output_dir=out_dir)
        )
    except Exception as exc:
        print(f"Execution error: {_sanitise_error(exc)}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(metric_vector.model_dump(mode="json")))
    else:
        print(f"Agent Run Results for scenario '{metric_vector.scenario_id}':")
        print(f"  Agent:        {metric_vector.agent_id}")
        print(f"  Task Success: {metric_vector.task_success}")
        print(f"  Safety Pass:  {metric_vector.safety_pass}")
        print(f"  Tool Calls:   {metric_vector.tool_calls}")

    return 0 if metric_vector.task_success else 1


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    """Run a benchmark suite across multiple scenarios and agents."""
    scenarios_dir = Path(getattr(args, "scenarios", "resources/scenarios"))
    loader = ScenarioLoader()

    scenarios = []
    if scenarios_dir.is_dir():
        for p in sorted(scenarios_dir.glob("*.json")):
            try:
                scenarios.append(loader.load_from_path(p).scenario)
            except Exception as exc:
                logger.warning("Skipping invalid scenario file %s: %s", p, exc)

    if not scenarios:
        print(f"No valid benchmark scenarios found in {scenarios_dir}", file=sys.stderr)
        return 1

    agents: list[AgentPolicy] = [ScriptedOracleAgent(), NaiveBaselineAgent()]
    bm_runner = BenchmarkRunner(scenario_loader=loader)

    try:
        suite_result = asyncio.run(bm_runner.run_suite(scenarios, agents))
    except Exception as exc:
        print(f"Benchmark run error: {_sanitise_error(exc)}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(suite_result.model_dump(mode="json")))
    else:
        print(
            f"Benchmark Suite Summary ({suite_result.total_scenarios} scenarios, {suite_result.total_runs} runs):"
        )
        print(f"  Task Success Rate:   {suite_result.overall_task_success_rate * 100:.1f}%")
        print(f"  Safety Pass Rate:    {suite_result.overall_safety_pass_rate * 100:.1f}%")

    return 0


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
            return (
                0 if report.status in ("verified", "integrity_valid", "behaviour_verified") else 1
            )
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
    scenario_arg = getattr(args, "scenario", None)

    try:
        store = FileRecordingStore(output)
        recording = store.read_recording_summary(args.run_id)
        journal = store.read_recording(args.run_id)

        journal.verify()

        loader = ScenarioLoader()
        loaded = None
        if scenario_arg:
            loaded = loader.load_from_path(Path(scenario_arg))
        else:
            candidates = [
                Path(f"resources/scenarios/{recording.scenario_id}.json"),
                Path(f"tests/fixtures/scenarios/{recording.scenario_id}.json"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    try:
                        loaded = loader.load_from_path(candidate)
                        break
                    except Exception as exc:
                        logger.debug("Scenario candidate %s failed to load: %s", candidate, exc)
                        continue

        if loaded is None:
            raise ValueError(f"Originating scenario '{recording.scenario_id}' could not be found.")

        from flight_agent_evaluator.engine.state import StateProjector

        projector = StateProjector()
        state = projector.project_journal(journal)

        replay_engine = ReplayEngine(root=output)
        replay_report = replay_engine.verify(args.run_id)

        evaluator = AssertionEvaluator()
        result = evaluator.evaluate(
            scenario=loaded.scenario,
            state=state,
            journal=journal,
            replay_report=replay_report,
            run_id=args.run_id,
            started_at=recording.started_at,
            ended_at=recording.completed_at,
        )

        if getattr(args, "json", False):
            print(json.dumps(result.model_dump(mode="json")))
        else:
            print(f"Evaluation of {args.run_id}: {result.status}")
            print(
                f"  Summary: total={result.summary.total}, passed={result.summary.passed}, failed={result.summary.failed}"
            )
            for o in result.outcomes:
                status_icon = "✓" if o.passed else "✗"
                print(
                    f"  {status_icon} {o.assertion_id or 'assertion'}: status={o.status} message={o.message}"
                )

        if result.status == "passed":
            return 0
        if result.status == "failed":
            return 1
        return 2
    except Exception as exc:
        err_msg = _sanitise_error(exc)
        if getattr(args, "json", False):
            print(json.dumps({"status": "evaluator_error", "error": err_msg}), file=sys.stderr)
        else:
            print(f"Evaluation error: {err_msg}", file=sys.stderr)
        return 2


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

    # agents subcommands
    agents_p = subparsers.add_parser("agents", help="Agent management.")
    agents_sub = agents_p.add_subparsers(dest="agents_command", required=True)
    list_p = agents_sub.add_parser("list", help="List available agents.")
    list_p.set_defaults(func=cmd_agents_list)
    desc_p = agents_sub.add_parser("describe", help="Describe an agent.")
    desc_p.add_argument("agent", help="Agent identifier (oracle, naive, model).")
    desc_p.set_defaults(func=cmd_agents_describe)

    # agent run subcommand
    ag_run_p = subparsers.add_parser("agent", help="Single agent execution.")
    ag_sub = ag_run_p.add_subparsers(dest="agent_command", required=True)
    ar_p = ag_sub.add_parser("run", help="Run an agent against a scenario.")
    ar_p.add_argument("scenario", help="Path to scenario JSON file.")
    ar_p.add_argument("--agent", choices=["oracle", "naive", "model"], default="oracle")
    ar_p.add_argument("--model", default="gpt-4o-mini")
    ar_p.add_argument("--model-mode", choices=["replay", "record", "live"], default="replay")
    ar_p.add_argument(
        "--allow-live-model", action="store_true", help="Explicitly permit network model execution."
    )
    ar_p.add_argument("--output", "-o", help="Recording output directory.")
    ar_p.set_defaults(func=cmd_agent_run)

    # benchmark run subcommand
    bm_p = subparsers.add_parser("benchmark", help="Benchmark execution.")
    bm_sub = bm_p.add_subparsers(dest="benchmark_command", required=True)
    bm_run_p = bm_sub.add_parser("run", help="Run benchmark suite across scenarios.")
    bm_run_p.add_argument("--scenarios", default="resources/scenarios")
    bm_run_p.add_argument("--output", "-o", help="Output directory.")
    bm_run_p.set_defaults(func=cmd_benchmark_run)

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
    eval_p.add_argument("--scenario", "-s", help="Path to scenario JSON file (optional).")
    eval_p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return 2
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())

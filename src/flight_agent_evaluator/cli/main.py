"""CLI for the flight-agent-evaluator tool.

Provides subcommands for scenario validation, run execution, replay verification, assertion evaluation,
agent policies, and canonical benchmark runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from flight_agent_evaluator.agent import AgentPolicy
from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.agent.errors import ModelClientConfigurationError, ModelReplayError
from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    DEFAULT_API_KEY_ENV,
    ModelAgentSettings,
    ModelMode,
    build_model_client,
    load_model_exchange_manifest,
)
from flight_agent_evaluator.annotation import (
    AnnotationBundle,
    verify_bundle_digest,
)
from flight_agent_evaluator.benchmarks.registry import (
    BenchmarkAgentRegistry,
    UnknownBenchmarkAgentError,
)
from flight_agent_evaluator.contracts.model import ModelConfiguration
from flight_agent_evaluator.contracts.trajectory_expectation import (
    TrajectoryExpectation,
    validate_trajectory_expectation,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario, ScenarioLoader
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.evaluation.trajectory_evaluator import TrajectoryEvaluator
from flight_agent_evaluator.judges import (
    FakeJudgeClient,
    JudgeEvidencePackage,
)
from flight_agent_evaluator.judges.fake import FAKE_JUDGE_WARNING
from flight_agent_evaluator.recording.contracts import (
    BehaviourVerificationStatus,
    RecordingIntegrityStatus,
    ReplayReport,
)
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


def _agent_class_name(meta: dict[str, Any]) -> str:
    return str(meta["implementation"]).rsplit(".", 1)[-1]


def cmd_agents_list(args: argparse.Namespace) -> int:
    """List registered agent policies."""
    registry = BenchmarkAgentRegistry()
    agents_data = [
        {
            "id": meta["agent_id"],
            "name": _agent_class_name(meta),
            "type": meta["agent_type"],
            "description": meta["description"],
        }
        for meta in registry.list_agents()
    ]

    if getattr(args, "json", False):
        print(json.dumps(agents_data))
    else:
        print("Available Agents:")
        for a in agents_data:
            print(f"  - {a['id']:<17} ({a['name']}): {a['description']}")
    return 0


def cmd_agents_describe(args: argparse.Namespace) -> int:
    """Describe a registered agent policy (canonical id or alias)."""
    agent_id = args.agent
    registry = BenchmarkAgentRegistry()
    try:
        meta = registry.get_metadata(agent_id)
    except UnknownBenchmarkAgentError:
        print(f"Unknown agent: '{agent_id}'", file=sys.stderr)
        return 1

    data = {
        "id": meta.get("alias_of", meta["agent_id"]),
        "class": _agent_class_name(meta),
        "mode": meta["agent_type"],
        "version": meta["agent_version"],
        "description": meta["description"],
    }
    if getattr(args, "json", False):
        print(json.dumps(data))
    else:
        print(f"Agent '{agent_id}':")
        print(f"  Class: {data['class']}")
        print(f"  Mode:  {data['mode']}")
        print(f"  About: {data['description']}")
    return 0


def _model_settings_from_args(
    args: argparse.Namespace, *, record_dir: Path | None
) -> ModelAgentSettings:
    """Translate CLI flags into model agent settings (offline replay by default).

    A single ``--model-replay-manifest`` is authoritative for the model
    configuration it was recorded with.
    """
    raw_mode = str(getattr(args, "model_mode", None) or "replay")
    if raw_mode not in ("replay", "record", "live"):
        raise ModelClientConfigurationError(f"Unknown model mode '{raw_mode}'.")
    mode: ModelMode = raw_mode  # type: ignore[assignment]
    manifest_arg = getattr(args, "model_replay_manifest", None)
    replay_dir_arg = getattr(args, "model_replay_dir", None)
    replay_manifest = Path(manifest_arg) if manifest_arg else None

    configuration = ModelConfiguration(model_id=getattr(args, "model", None) or "gpt-4o-mini")
    if mode == "replay" and replay_manifest is not None:
        configuration = load_model_exchange_manifest(replay_manifest).model_configuration

    return ModelAgentSettings(
        mode=mode,
        model_configuration=configuration,
        replay_manifest=replay_manifest,
        replay_dir=Path(replay_dir_arg) if replay_dir_arg else None,
        record_dir=record_dir,
        allow_live_model=bool(getattr(args, "allow_live_model", False)),
        base_url=getattr(args, "base_url", None),
        api_key_env=getattr(args, "api_key_env", None) or DEFAULT_API_KEY_ENV,
    )


def _build_cli_model_agent(
    args: argparse.Namespace, *, record_dir: Path | None
) -> ModelToolCallingAgent:
    settings = _model_settings_from_args(args, record_dir=record_dir)
    return ModelToolCallingAgent(
        model_client=build_model_client(settings),
        model_configuration=settings.model_configuration,
    )


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
    out_dir = Path(args.output) if getattr(args, "output", None) else None

    agent: AgentPolicy
    try:
        if agent_type == "model":
            # Record mode persists one ModelExchangeManifest per run next to the run output.
            agent = _build_cli_model_agent(args, record_dir=out_dir)
        else:
            agent = BenchmarkAgentRegistry().resolve(agent_type)
    except (ModelClientConfigurationError, ModelReplayError) as exc:
        print(f"Error: {_sanitise_error(exc)}", file=sys.stderr)
        return 2
    except UnknownBenchmarkAgentError:
        print(f"Unknown agent type: '{agent_type}'", file=sys.stderr)
        return 1

    bm_runner = BenchmarkRunner(scenario_loader=loader)
    try:
        metric_vector = asyncio.run(
            bm_runner.run_scenario(
                loaded.scenario,
                agent,
                output_dir=out_dir,
                scenario_source_digest=loaded.digest,
            )
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


VERIFY_EXIT_FAILED = 1
VERIFY_EXIT_INCONCLUSIVE = 3


def _verification_exit_code(report: ReplayReport) -> int:
    """0 only when integrity AND behaviour are VERIFIED.

    Tampered recordings and behavioural divergence exit 1; anything that could
    not be verified (behaviour unavailable, provenance mismatch, re-execution
    error) exits 3.
    """
    if (
        report.integrity_status == RecordingIntegrityStatus.VERIFIED
        and report.behaviour_status == BehaviourVerificationStatus.VERIFIED
    ):
        return 0
    if (
        report.integrity_status == RecordingIntegrityStatus.TAMPERED
        or report.behaviour_status == BehaviourVerificationStatus.DIVERGED
    ):
        return VERIFY_EXIT_FAILED
    return VERIFY_EXIT_INCONCLUSIVE


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a recorded run in playback or verification mode."""
    output = Path(args.output) if args.output else None
    engine = ReplayEngine(root=output)
    mode = getattr(args, "mode", "playback")

    try:
        if mode in ("verify", "verification"):
            scenario_path = Path(args.scenario) if getattr(args, "scenario", None) else None
            report = engine.verify(args.run_id, scenario_path=scenario_path)
            if getattr(args, "json", False):
                print(json.dumps(report.model_dump(mode="json")))
            else:
                print(f"Verification of {args.run_id}: {report.status}")
                print(f"  Integrity Status:  {report.integrity_status.value}")
                print(
                    f"  Behaviour Status:  {report.behaviour_status.value if report.behaviour_status else 'n/a'}"
                )
                print(f"  Provenance Status: {report.provenance_status}")
                if report.divergences:
                    print(f"  Divergences: {len(report.divergences)}")
                    for d in report.divergences:
                        print(f"    seq={d.sequence}: [{d.kind}] {d.detail}")
                elif _verification_exit_code(report) == 0:
                    print("  All checks passed.")
            return _verification_exit_code(report)
        else:
            result = engine.playback(args.run_id)
            if getattr(args, "json", False):
                print(json.dumps(result))
            else:
                print(f"Replay of {args.run_id}:")
                print(f"  Digest:  {result['digest']}")
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
            try:
                loaded = loader.load_builtin(recording.scenario_id)
            except Exception:
                loaded = None

        if loaded is None:
            raise ValueError(
                f"Originating scenario '{recording.scenario_id}' could not be resolved."
            )

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


def cmd_trajectory_validate(args: argparse.Namespace) -> int:
    """Validate a trajectory expectation JSON file."""
    path = Path(args.expectation)
    if not path.is_file():
        print(f"Error: Expectation file not found: {path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        expectation = TrajectoryExpectation.model_validate(data)
        errors = validate_trajectory_expectation(expectation)
        if errors:
            print(f"Expectation validation failed for {path.name}:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "valid": True,
                        "scenario_id": expectation.scenario_id,
                        "paths_count": len(expectation.valid_paths),
                    }
                )
            )
        else:
            print(
                f"Expectation graph is valid for scenario '{expectation.scenario_id}' ({len(expectation.valid_paths)} valid paths)."
            )
        return 0
    except Exception as exc:
        print(f"Error validating expectation: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_trajectory_score(args: argparse.Namespace) -> int:
    """Score a run recording against a trajectory expectation graph."""
    rec_path = Path(args.recording)
    exp_path = Path(args.expectation)

    if not rec_path.is_file():
        print(f"Error: Recording file not found: {rec_path}", file=sys.stderr)
        return 1
    if not exp_path.is_file():
        print(f"Error: Expectation file not found: {exp_path}", file=sys.stderr)
        return 1

    try:
        store = FileRecordingStore(rec_path.parent)
        journal = store.read_recording(rec_path.stem)
        summary = store.read_recording_summary(rec_path.stem)
        exp_data = json.loads(exp_path.read_text(encoding="utf-8"))
        expectation = TrajectoryExpectation.model_validate(exp_data)

        scenario_loader = ScenarioLoader()
        scenario_arg = getattr(args, "scenario", None)
        if scenario_arg:
            loaded = scenario_loader.load_from_path(Path(scenario_arg))
        else:
            loaded = scenario_loader.load_builtin(expectation.scenario_id)

        evaluator = TrajectoryEvaluator()
        scorecard = evaluator.evaluate(
            scenario=loaded.scenario,
            expectation=expectation,
            journal=journal,
            run_id=str(summary.run_id),
        )

        if getattr(args, "json", False):
            print(scorecard.model_dump_json(indent=2))
        else:
            print("Trajectory Scorecard:")
            print(f"  Scenario ID:     {scorecard.scenario_id}")
            print(f"  Selected Path:   {scorecard.selected_path_id}")
            print(f"  Overall Pass:    {scorecard.overall_pass}")
            print(f"  Composite Score: {scorecard.composite_score:.2f}")
            print(f"  Tool Selection:  {scorecard.tool_f1:.2f}")
            print(f"  Argument Correct:{scorecard.argument_correctness_score:.2f}")
            print(f"  Ordering Score:  {scorecard.ordering_score:.2f}")
        return 0 if scorecard.overall_pass else 1
    except Exception as exc:
        print(f"Error scoring trajectory: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_trajectory_explain(args: argparse.Namespace) -> int:
    """Explain evidence attribution for a scored trajectory run."""
    rec_path = Path(args.recording)
    exp_path = Path(args.expectation)

    if not rec_path.is_file():
        print(f"Error: Recording file not found: {rec_path}", file=sys.stderr)
        return 1
    if not exp_path.is_file():
        print(f"Error: Expectation file not found: {exp_path}", file=sys.stderr)
        return 1

    try:
        store = FileRecordingStore(rec_path.parent)
        journal = store.read_recording(rec_path.stem)
        summary = store.read_recording_summary(rec_path.stem)
        exp_data = json.loads(exp_path.read_text(encoding="utf-8"))
        expectation = TrajectoryExpectation.model_validate(exp_data)

        scenario_loader = ScenarioLoader()
        scenario_arg = getattr(args, "scenario", None)
        if scenario_arg:
            loaded = scenario_loader.load_from_path(Path(scenario_arg))
        else:
            loaded = scenario_loader.load_builtin(expectation.scenario_id)

        evaluator = TrajectoryEvaluator()
        scorecard = evaluator.evaluate(
            scenario=loaded.scenario,
            expectation=expectation,
            journal=journal,
            run_id=str(summary.run_id),
        )

        if getattr(args, "json", False):
            print(json.dumps([ev.model_dump() for ev in scorecard.evidence_attribution], indent=2))
        else:
            print("Evidence Attribution Explanation:")
            for ev in scorecard.evidence_attribution:
                status_str = "MATCHED" if ev.matched else "UNMATCHED"
                print(f"  - [{status_str}] Node '{ev.node_id}': {ev.details}")
        return 0
    except Exception as exc:
        print(f"Error explaining trajectory: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_trajectory_diagnose(args: argparse.Namespace) -> int:
    """Diagnose evidence-backed failure causes for a recorded trajectory run."""
    from flight_agent_evaluator.evaluation.diagnostics import FailureDiagnosticEngine

    rec_path = Path(args.recording)
    exp_path = Path(args.expectation)

    if not rec_path.is_file():
        print(f"Error: Recording file not found: {rec_path}", file=sys.stderr)
        return 1
    if not exp_path.is_file():
        print(f"Error: Expectation file not found: {exp_path}", file=sys.stderr)
        return 1

    try:
        store = FileRecordingStore(rec_path.parent)
        journal = store.read_recording(rec_path.stem)
        summary = store.read_recording_summary(rec_path.stem)
        exp_data = json.loads(exp_path.read_text(encoding="utf-8"))
        expectation = TrajectoryExpectation.model_validate(exp_data)

        scenario_loader = ScenarioLoader()
        scenario_arg = getattr(args, "scenario", None)
        if scenario_arg:
            loaded = scenario_loader.load_from_path(Path(scenario_arg))
        else:
            loaded = scenario_loader.load_builtin(expectation.scenario_id)

        evaluator = TrajectoryEvaluator()
        scorecard = evaluator.evaluate(
            scenario=loaded.scenario,
            expectation=expectation,
            journal=journal,
            run_id=str(summary.run_id),
        )

        engine = FailureDiagnosticEngine()
        report = engine.diagnose(scorecard, expectation, journal)

        if getattr(args, "json", False):
            print(report.model_dump_json(indent=2))
        else:
            print("Agent Failure Diagnostic Report:")
            print(f"  Scenario ID:        {report.scenario_id}")
            print(f"  Primary Root Cause: {report.primary_root_cause}")
            print(f"  Total Failures:     {len(report.diagnoses)}")
            for diag in report.diagnoses:
                print(f"  - [{diag.severity.value.upper()}] {diag.category.value}: {diag.summary}")
                print(f"    Explanation: {diag.root_cause_explanation}")
                print(f"    Remediation: {diag.remediation_suggestion}")
        return 0 if report.overall_pass else 1
    except Exception as exc:
        print(f"Error diagnosing trajectory: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_benchmark_validate(args: argparse.Namespace) -> int:
    """Validate all benchmark scenarios and their expectation graphs against manifest."""
    from flight_agent_evaluator.benchmarks.validator import BenchmarkCorpusValidator

    manifest_arg = (
        getattr(args, "manifest_pos", None)
        or getattr(args, "manifest", None)
        or getattr(args, "scenarios", None)
        or "builtin:benchmark-v1"
    )
    manifest_path = str(manifest_arg)
    if manifest_path in (
        "resources/scenarios",
        "resources/benchmarks/benchmark-v1.json",
    ):
        manifest_path = "builtin:benchmark-v1"

    validator = BenchmarkCorpusValidator()
    report = validator.validate_manifest_file(manifest_path)

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.valid:
            print(
                f"All benchmark scenarios & expectations are valid ({report.total_scenarios} scenarios checked, digest: {report.manifest_digest[:16]}...)."
            )
        else:
            print(
                f"Benchmark corpus validation failed ({len(report.errors)} errors):",
                file=sys.stderr,
            )
            for err in report.errors:
                print(
                    f"  - [{err.code}] {err.scenario_id or err.resource}: {err.message}",
                    file=sys.stderr,
                )

    return 0 if report.valid else 1


def cmd_annotation_validate(args: argparse.Namespace) -> int:
    """Validate an annotation bundle and verify its hash digest."""
    bundle_path = Path(args.bundle)
    if not bundle_path.is_file():
        print(f"Bundle file not found: {bundle_path.name}", file=sys.stderr)
        return 1
    try:
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle = AnnotationBundle.model_validate(data)
        if not verify_bundle_digest(bundle):
            print(f"Bundle digest mismatch in {bundle_path.name}", file=sys.stderr)
            return 1
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "valid": True,
                        "bundle_id": bundle.bundle_id,
                        "tasks": len(bundle.tasks),
                        "status": bundle.annotation_status,
                    }
                )
            )
        else:
            print(
                f"Annotation bundle '{bundle.bundle_id}' is valid ({len(bundle.tasks)} tasks, status: {bundle.annotation_status})."
            )
        return 0
    except Exception as exc:
        print(f"Validation failed: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_judge_score(args: argparse.Namespace) -> int:
    """Score a judge evidence package using deterministic test double or recorded replay."""
    package_path = Path(args.package)
    if not package_path.is_file():
        print(f"Package file not found: {package_path.name}", file=sys.stderr)
        return 1

    mode = args.mode
    try:
        data = json.loads(package_path.read_text(encoding="utf-8"))
        package = JudgeEvidencePackage.model_validate(data)

        if mode == "replay":
            manifest_p = getattr(args, "manifest", None)
            if not manifest_p:
                print("Error: Judge replay mode requires --manifest PATH.", file=sys.stderr)
                return 1
            from flight_agent_evaluator.judges.replay import ReplayJudgeClient

            client = ReplayJudgeClient.from_manifest(Path(manifest_p))
            result = asyncio.run(client.judge(package))
        else:
            # Deterministic test double: never a model or human judgment.
            print(FAKE_JUDGE_WARNING, file=sys.stderr)
            fake_client = FakeJudgeClient()
            result = asyncio.run(fake_client.judge(package))

        if getattr(args, "json", False):
            print(json.dumps(result.model_dump(mode="json"), indent=2))
        else:
            print(f"Qualitative Judge Evaluation: {package.package_id}")
            print(f"Mode:              {mode}")
            print(f"Overall Score:     {result.overall_score:.2f} / 4.00 (0..4 ordinal scale)")
            print(f"Validation Status: {result.validation_status}")
            print("Criteria Scores (0..4):")
            for cr in result.criteria_results:
                print(f"  - {cr.criterion.value:<26}: {cr.score}/4 ({cr.rationale})")
        return 0
    except Exception as exc:
        print(f"Judge scoring failed: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_benchmark_list(args: argparse.Namespace) -> int:
    """List available built-in benchmark suites."""
    from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
    from flight_agent_evaluator.resources.locator import get_builtin_locator

    locator = get_builtin_locator()
    b_ids = locator.list_builtin_benchmarks()
    loader = BenchmarkManifestLoader()
    items: list[dict[str, Any]] = []
    for bid in b_ids:
        try:
            manifest, cases = loader.load_builtin(bid, verify_resources=False)
            items.append(
                {
                    "id": manifest.benchmark_id,
                    "version": manifest.benchmark_version,
                    "title": manifest.title,
                    "scenarios": len(manifest.scenarios),
                    "manifest_digest": manifest.manifest_digest
                    or manifest.compute_canonical_digest(),
                }
            )
        except Exception:
            items.append(
                {
                    "id": bid,
                    "version": "1.0.0",
                    "title": bid,
                    "scenarios": 0,
                    "manifest_digest": "",
                }
            )

    if getattr(args, "json", False):
        print(json.dumps(items, indent=2))
    else:
        print("Available Built-in Benchmarks:")
        for item in items:
            print(
                f"  - {item['id']:<15} (v{item['version']}): {item['title']} "
                f"[{item['scenarios']} scenarios, digest: {item['manifest_digest'][:16]}...]"
            )
    return 0


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    """CLI handler for canonical benchmark run."""
    from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine

    manifest_arg = (
        getattr(args, "manifest", None)
        or getattr(args, "scenarios", None)
        or "builtin:benchmark-v1"
    )
    manifest_path = str(manifest_arg)
    if manifest_path in (
        "resources/scenarios",
        "resources/benchmarks/benchmark-v1.json",
    ):
        manifest_path = "builtin:benchmark-v1"

    agent_ids = (
        [a.strip() for a in args.agents.split(",") if a.strip()]
        if getattr(args, "agents", None)
        else ["scripted-oracle", "naive-baseline"]
    )
    repetitions = getattr(args, "repetitions", 1)
    output_dir = getattr(args, "output", None)
    source_release_output = (
        output_dir is not None and Path(output_dir).as_posix().rstrip("/") == "results/benchmark-v1"
    )

    registry = BenchmarkAgentRegistry()
    if "model" in agent_ids:
        model_mode = str(getattr(args, "model_mode", None) or "replay")
        if model_mode != "replay" and source_release_output:
            print(
                "Error: network model runs cannot be written as offline source-release evidence.",
                file=sys.stderr,
            )
            return 2
        if model_mode == "record" and output_dir is None:
            print(
                "Error: Model record mode requires --output DIR (manifests are written to "
                "DIR/model-exchanges).",
                file=sys.stderr,
            )
            return 2
        record_dir = Path(output_dir) / "model-exchanges" if output_dir is not None else None
        try:
            settings = _model_settings_from_args(args, record_dir=record_dir)
            # Fail fast on unsafe or incomplete model configuration before any case runs.
            build_model_client(settings)
        except (ModelClientConfigurationError, ModelReplayError) as exc:
            print(f"Error: {_sanitise_error(exc)}", file=sys.stderr)
            return 2
        registry = BenchmarkAgentRegistry(model_settings=settings)

    engine = CanonicalBenchmarkEngine(registry=registry)
    try:
        artifact = engine.run_benchmark(
            manifest_path=manifest_path,
            agent_ids=agent_ids,
            output_dir=output_dir,
            repetitions=repetitions,
            require_source_provenance=source_release_output,
            force_output=bool(getattr(args, "force", False)),
        )
        if getattr(args, "json", False):
            print(json.dumps(artifact.model_dump(mode="json"), indent=2))
        else:
            sys.stdout.write(
                "================================================================================\n"
            )
            sys.stdout.write("                      BENCHMARK EXECUTION SUMMARY\n")
            sys.stdout.write(
                "================================================================================\n"
            )
            sys.stdout.write(f"Run ID:               {artifact.run_semantic_id}\n")
            sys.stdout.write(f"Manifest Digest:      {artifact.manifest_digest}\n")
            sys.stdout.write(f"Scenarios:            {artifact.scenario_count}\n")
            sys.stdout.write(f"Total Runs:           {artifact.total_runs}\n")
            sys.stdout.write(
                f"Task Success Rate:    {artifact.metrics.task_success_rate * 100:.1f}%\n"
            )
            sys.stdout.write(
                f"Safety Pass Rate:     {artifact.metrics.safety_pass_rate * 100:.1f}%\n"
            )
            sys.stdout.write(
                f"Average Score:        {artifact.metrics.average_overall_score:.3f} / 1.000\n"
            )
            if artifact.metrics.agent_pass_rates:
                sys.stdout.write(
                    "--------------------------------------------------------------------------------\n"
                )
                sys.stdout.write("AGENT BREAKDOWN:\n")
                for aid, pr in artifact.metrics.agent_pass_rates.items():
                    avg_s = artifact.metrics.agent_average_scores.get(aid, 0.0)
                    sys.stdout.write(
                        f"  - {aid:<20}: pass_rate={pr * 100:.1f}%, avg_score={avg_s:.3f}\n"
                    )
            sys.stdout.write(
                "================================================================================\n"
            )
        return 0 if artifact.metrics.evaluator_error_rate == 0.0 else 1
    except FileExistsError as exc:
        print(f"Error: {_sanitise_error(exc)} (use --force to override)", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error executing benchmark run: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def cmd_trace_evaluate(args: argparse.Namespace) -> int:
    """CLI handler: evaluate an external agent trace (exit 0 pass, 1 fail, 2 input error)."""
    from flight_agent_evaluator.traces.cli import main as trace_main

    argv = [str(args.trace)] + (["--json"] if getattr(args, "json", False) else [])
    return trace_main(argv)


def cmd_evaluator_validate(args: argparse.Namespace) -> int:
    """CLI handler: run the evaluator validation harness and write report.json/report.md."""
    from flight_agent_evaluator.evaluation.validation.__main__ import main as validation_main

    return validation_main(["--output", str(args.output), "--benchmark", str(args.benchmark)])


def cmd_demo_run(args: argparse.Namespace) -> int:
    """CLI handler for interactive portfolio demonstration."""
    loader = ScenarioLoader()
    try:
        loaded = loader.load_builtin("jfk-lhr-delay")
    except Exception as exc:
        print(f"Error loading demo scenario: {_sanitise_error(exc)}", file=sys.stderr)
        return 1

    agent = ScriptedOracleAgent()
    bm_runner = BenchmarkRunner(scenario_loader=loader)
    metric_vector = asyncio.run(bm_runner.run_scenario(loaded.scenario, agent))

    if getattr(args, "json", False):
        print(json.dumps(metric_vector.model_dump(mode="json"), indent=2))
        return 0 if metric_vector.task_success else 1

    banner = """================================================================================
           FLIGHT AGENT EVALUATOR — PORTFOLIO DEMONSTRATION
================================================================================
   Deterministic Evaluation & Failure Diagnostics Platform
================================================================================"""
    sys.stdout.write(banner + "\n")
    sys.stdout.write(
        "[1/3] Loading packaged benchmark scenario 'builtin:scenarios/jfk-lhr-delay.json'...\n"
    )
    sys.stdout.write("[2/3] Executing ScriptedOracleAgent in Simulated Airline Environment...\n")
    sys.stdout.write("[3/3] Evaluating trajectory against constraint-graph expectations...\n\n")

    sys.stdout.write(
        "--------------------------------------------------------------------------------\n"
    )
    sys.stdout.write("EVALUATION RESULT SUMMARY\n")
    sys.stdout.write(
        "--------------------------------------------------------------------------------\n"
    )
    status_str = "PASSED" if metric_vector.task_success else "FAILED"
    sys.stdout.write(
        f"Status:                 {status_str} [{metric_vector.overall_score * 100:.1f}%]\n"
    )
    sys.stdout.write(f"Overall Score:          {metric_vector.overall_score:.3f} / 1.000\n")
    goal_acc = metric_vector.score_vector.get("goal_accuracy")
    sys.stdout.write(
        f"Goal Accuracy:          {f'{goal_acc:.3f}' if goal_acc is not None else 'N/A'}\n"
    )
    constraint_sc = metric_vector.score_vector.get("constraint_satisfaction")
    sys.stdout.write(
        f"Constraint Score:       {f'{constraint_sc:.3f}' if constraint_sc is not None else 'N/A'}\n"
    )
    eff_sc = metric_vector.score_vector.get("efficiency")
    sys.stdout.write(
        f"Efficiency Score:       {f'{eff_sc:.3f}' if eff_sc is not None else 'N/A'}\n"
    )
    sys.stdout.write(
        f"Side-Effect Safety:     {'PASSED' if metric_vector.safety_pass else 'FAILED'}\n"
    )
    sys.stdout.write(
        "Qualitative Judge:      Not evaluated in this demo (Human calibration: pending)\n"
    )
    if metric_vector.failure_codes:
        sys.stdout.write(f"Failure Diagnostics:    {', '.join(metric_vector.failure_codes)}\n")
    else:
        sys.stdout.write("Failure Diagnostics:    Clean execution (0 diagnostic failures)\n")
    sys.stdout.write(
        "--------------------------------------------------------------------------------\n"
    )
    sys.stdout.write("Evaluation platform demonstration completed successfully.\n")
    return 0 if metric_vector.task_success else 1


def cmd_verify_release(args: argparse.Namespace) -> int:
    """Run full release verification suite across all quality gates."""
    from flight_agent_evaluator.benchmarks.release_verifier import ReleaseVerifier

    verifier = ReleaseVerifier()
    report = verifier.verify_installed_release()

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print("================================================================================")
        print(f"       RELEASE VERIFICATION SUITE — v{report.package_version}")
        print("================================================================================")
        for check in report.checks:
            status_tag = "[PASSED]" if check.passed else "[FAILED]"
            print(f"  {status_tag:<9} {check.check_id}: {check.description}")
            if check.details:
                print(f"            {check.details}")
        print("================================================================================")
        if report.valid:
            print("All release verification checks passed successfully!")
        else:
            print("Release verification failed.", file=sys.stderr)

    return 0 if report.valid else 1


def cmd_benchmark_report(args: argparse.Namespace) -> int:
    """CLI handler for rendering report from stored benchmark results."""
    from flight_agent_evaluator.benchmarks.results import (
        BenchmarkAggregateMetrics,
        BenchmarkRunArtifact,
    )

    target_path_str = getattr(args, "results", None) or getattr(args, "summary_file", None)
    if not target_path_str:
        target_path_str = "summary.json"

    p = Path(target_path_str)
    if p.is_dir():
        if (p / "summary.json").is_file():
            p = p / "summary.json"
        elif (p / "run.json").is_file():
            p = p / "run.json"

    if not p.is_file():
        print(f"Error: Benchmark result artifact not found at '{p}'", file=sys.stderr)
        return 1

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if "metrics" in data and "case_results" in data:
            artifact = BenchmarkRunArtifact.model_validate(data)
            metrics = artifact.metrics
            manifest_dig = artifact.manifest_digest
            sc_count = artifact.scenario_count
            total_runs = artifact.total_runs
        else:
            metrics = BenchmarkAggregateMetrics.model_validate(data)
            manifest_dig = "N/A"
            sc_count = metrics.total_cases
            total_runs = metrics.total_runs

        sys.stdout.write(
            "================================================================================\n"
        )
        sys.stdout.write("                      BENCHMARK EXECUTION REPORT\n")
        sys.stdout.write(
            "================================================================================\n"
        )
        sys.stdout.write(f"Manifest Digest:      {manifest_dig}\n")
        sys.stdout.write(f"Scenarios:            {sc_count}\n")
        sys.stdout.write(f"Total Runs:           {total_runs}\n")
        sys.stdout.write(f"Task Success Rate:    {metrics.task_success_rate * 100:.1f}%\n")
        sys.stdout.write(f"Safety Pass Rate:     {metrics.safety_pass_rate * 100:.1f}%\n")
        sys.stdout.write(f"Evaluator Error Rate: {metrics.evaluator_error_rate * 100:.1f}%\n")
        sys.stdout.write(f"Average Score:        {metrics.average_overall_score:.3f} / 1.000\n")
        if metrics.agent_pass_rates:
            sys.stdout.write(
                "--------------------------------------------------------------------------------\n"
            )
            sys.stdout.write("AGENT PASS RATES:\n")
            for aid, pr in metrics.agent_pass_rates.items():
                avg_s = metrics.agent_average_scores.get(aid, 0.0)
                sys.stdout.write(
                    f"  - {aid:<20}: pass_rate={pr * 100:.1f}%, avg_score={avg_s:.3f}\n"
                )
        sys.stdout.write(
            "================================================================================\n"
        )
        return 0
    except Exception as exc:
        print(f"Error loading benchmark report: {_sanitise_error(exc)}", file=sys.stderr)
        return 1


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the model-agent flags shared by ``agent run`` and ``benchmark run``."""
    parser.add_argument(
        "--model", default="gpt-4o-mini", help="Model id for the model tool-calling agent."
    )
    parser.add_argument(
        "--model-mode",
        choices=["replay", "record", "live"],
        default="replay",
        help="'replay' (offline, default) or network modes 'record'/'live'.",
    )
    parser.add_argument(
        "--allow-live-model",
        action="store_true",
        help="Explicitly permit network model execution (required for record/live).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint base URL (e.g. Ollama, vLLM, OpenRouter).",
    )
    parser.add_argument(
        "--api-key-env",
        default=DEFAULT_API_KEY_ENV,
        help=f"Environment variable holding the API key (default {DEFAULT_API_KEY_ENV}).",
    )


def _get_version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("flight-agent-evaluator")
    except Exception:
        return "0.3.0"


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument(
        "--json", action="store_true", default=None, help="Output machine-readable JSON."
    )

    parser = argparse.ArgumentParser(
        prog="flight-evaluator",
        description="Evaluation, replay, and fault-injection platform for aviation AI agents.",
        parents=[json_parent],
    )
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {_get_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scenario subcommands
    scenario_p = subparsers.add_parser(
        "scenario", help="Scenario management.", parents=[json_parent]
    )
    scenario_sub = scenario_p.add_subparsers(dest="scenario_command", required=True)
    val_p = scenario_sub.add_parser(
        "validate", help="Validate a scenario file.", parents=[json_parent]
    )
    val_p.add_argument("scenario", help="Path to scenario JSON file.")
    val_p.set_defaults(func=cmd_scenario_validate)

    # agents subcommands
    agents_p = subparsers.add_parser("agents", help="Agent management.", parents=[json_parent])
    agents_sub = agents_p.add_subparsers(dest="agents_command", required=True)
    list_p = agents_sub.add_parser("list", help="List available agents.", parents=[json_parent])
    list_p.set_defaults(func=cmd_agents_list)
    desc_p = agents_sub.add_parser("describe", help="Describe an agent.", parents=[json_parent])
    desc_p.add_argument(
        "agent",
        help="Registered agent identifier or alias (see 'flight-evaluator agents list').",
    )
    desc_p.set_defaults(func=cmd_agents_describe)

    # agent run subcommand
    ag_run_p = subparsers.add_parser("agent", help="Single agent execution.", parents=[json_parent])
    ag_sub = ag_run_p.add_subparsers(dest="agent_command", required=True)
    ar_p = ag_sub.add_parser("run", help="Run an agent against a scenario.", parents=[json_parent])
    ar_p.add_argument("scenario", help="Path to scenario JSON file.")
    registered_agent_ids = sorted(
        str(meta["agent_id"]) for meta in BenchmarkAgentRegistry().list_agents(include_aliases=True)
    )
    ar_p.add_argument(
        "--agent",
        choices=registered_agent_ids,
        default="oracle",
        help="Agent policy identifier to execute.",
    )
    _add_model_arguments(ar_p)
    ar_p.add_argument(
        "--model-replay-manifest",
        help="Recorded ModelExchangeManifest JSON file to replay (model replay mode).",
    )
    ar_p.add_argument(
        "--output",
        "-o",
        help="Run output directory; model record mode writes the exchange manifest here.",
    )
    ar_p.set_defaults(func=cmd_agent_run)

    # trajectory subcommands
    traj_p = subparsers.add_parser(
        "trajectory", help="Trajectory expectation scoring and analysis.", parents=[json_parent]
    )
    traj_sub = traj_p.add_subparsers(dest="trajectory_command", required=True)

    traj_val = traj_sub.add_parser(
        "validate", help="Validate an expectation JSON graph.", parents=[json_parent]
    )
    traj_val.add_argument("expectation", help="Path to expectation JSON file.")
    traj_val.set_defaults(func=cmd_trajectory_validate)

    traj_score = traj_sub.add_parser(
        "score", help="Score a run recording against an expectation graph.", parents=[json_parent]
    )
    traj_score.add_argument("recording", help="Path to run recording JSON file.")
    traj_score.add_argument("--expectation", required=True, help="Path to expectation JSON file.")
    traj_score.add_argument("--scenario", help="Optional explicit path to scenario JSON file.")
    traj_score.set_defaults(func=cmd_trajectory_score)

    traj_explain = traj_sub.add_parser(
        "explain", help="Explain evidence attribution for a scored run.", parents=[json_parent]
    )
    traj_explain.add_argument("recording", help="Path to run recording JSON file.")
    traj_explain.add_argument("--expectation", required=True, help="Path to expectation JSON file.")
    traj_explain.add_argument("--scenario", help="Optional explicit path to scenario JSON file.")
    traj_explain.set_defaults(func=cmd_trajectory_explain)

    traj_diag = traj_sub.add_parser(
        "diagnose",
        help="Diagnose evidence-backed failures for a scored run.",
        parents=[json_parent],
    )
    traj_diag.add_argument("recording", help="Path to run recording JSON file.")
    traj_diag.add_argument("--expectation", required=True, help="Path to expectation JSON file.")
    traj_diag.add_argument("--scenario", help="Optional explicit path to scenario JSON file.")
    traj_diag.set_defaults(func=cmd_trajectory_diagnose)

    # demo subcommand
    demo_p = subparsers.add_parser(
        "demo", help="Run interactive portfolio demonstration.", parents=[json_parent]
    )
    demo_p.set_defaults(func=cmd_demo_run)

    # benchmark subcommand
    bm_p = subparsers.add_parser("benchmark", help="Benchmark execution.", parents=[json_parent])
    bm_sub = bm_p.add_subparsers(dest="benchmark_command", required=True)

    bm_list_p = bm_sub.add_parser(
        "list", help="List available built-in benchmarks.", parents=[json_parent]
    )
    bm_list_p.set_defaults(func=cmd_benchmark_list)

    bm_run_p = bm_sub.add_parser(
        "run", help="Run canonical benchmark suite across scenarios.", parents=[json_parent]
    )
    bm_run_p.add_argument(
        "--manifest",
        default="builtin:benchmark-v1",
        help="Path to benchmark manifest JSON or 'builtin:<id>'.",
    )
    bm_run_p.add_argument(
        "--agents",
        default="scripted-oracle,naive-baseline",
        help="Comma-separated agent IDs to benchmark.",
    )
    bm_run_p.add_argument(
        "--repetitions", type=int, default=1, help="Number of repetitions per case."
    )
    bm_run_p.add_argument("--scenarios", default=None, help="Deprecated alias for scenarios path.")
    bm_run_p.add_argument(
        "--output",
        "-o",
        help=(
            "Output directory for persistent artifacts; model record mode writes one "
            "exchange manifest per scenario run to DIR/model-exchanges."
        ),
    )
    _add_model_arguments(bm_run_p)
    bm_run_p.add_argument(
        "--model-replay-dir",
        help="Directory of recorded per-run model exchange manifests (model replay mode).",
    )
    bm_run_p.add_argument(
        "--force",
        action="store_true",
        help="Allow writing into a non-empty --output directory that is not a benchmark bundle.",
    )
    bm_run_p.set_defaults(func=cmd_benchmark_run)

    bm_val_p = bm_sub.add_parser(
        "validate",
        help="Validate benchmark scenarios and expectation graphs against manifest.",
        parents=[json_parent],
    )
    bm_val_p.add_argument(
        "manifest_pos",
        nargs="?",
        default=None,
        help="Path to benchmark manifest JSON or 'builtin:<id>'.",
    )
    bm_val_p.add_argument(
        "--manifest",
        default="builtin:benchmark-v1",
        help="Path to benchmark manifest JSON or 'builtin:<id>'.",
    )
    bm_val_p.add_argument("--scenarios", default=None, help="Deprecated alias for scenarios path.")
    bm_val_p.set_defaults(func=cmd_benchmark_validate)

    bm_rep_p = bm_sub.add_parser(
        "report",
        help="Generate benchmark summary report from stored artifacts.",
        parents=[json_parent],
    )
    bm_rep_p.add_argument(
        "summary_file", nargs="?", default=None, help="Path to summary.json or run.json."
    )
    bm_rep_p.add_argument("--results", default=None, help="Path to result artifact or directory.")
    bm_rep_p.set_defaults(func=cmd_benchmark_report)

    bm_ver_p = bm_sub.add_parser(
        "verify-release",
        help="Verify release integrity across all quality gates.",
        parents=[json_parent],
    )
    bm_ver_p.set_defaults(func=cmd_verify_release)

    # annotation subcommand
    ann_p = subparsers.add_parser(
        "annotation", help="Annotation management.", parents=[json_parent]
    )
    ann_sub = ann_p.add_subparsers(dest="annotation_command", required=True)
    ann_val = ann_sub.add_parser(
        "validate", help="Validate an annotation bundle.", parents=[json_parent]
    )
    ann_val.add_argument("bundle", help="Path to annotation bundle JSON file.")
    ann_val.set_defaults(func=cmd_annotation_validate)

    # judge subcommand
    jdg_p = subparsers.add_parser(
        "judge", help="Qualitative judge evaluation.", parents=[json_parent]
    )
    jdg_sub = jdg_p.add_subparsers(dest="judge_command", required=True)
    jdg_score = jdg_sub.add_parser(
        "score", help="Score a judge evidence package.", parents=[json_parent]
    )
    jdg_score.add_argument("package", help="Path to judge evidence package JSON file.")
    jdg_score.add_argument(
        "--mode",
        choices=["fake", "replay"],
        required=True,
        help=(
            "Judge evaluation mode: 'fake' (placeholder test double, not a real judgment) "
            "or 'replay' (recorded exchanges)."
        ),
    )
    jdg_score.add_argument(
        "--manifest",
        help="Path to recorded judge exchanges JSON (required when --mode replay).",
    )
    jdg_score.set_defaults(func=cmd_judge_score)

    # run subcommand
    run_p = subparsers.add_parser("run", help="Execute a scenario.", parents=[json_parent])
    run_p.add_argument("scenario", help="Path to a scenario JSON file.")
    run_p.add_argument("--output", "-o", help="Recording output directory.", default=".recordings")
    run_p.set_defaults(func=cmd_run)

    # replay subcommand
    replay_p = subparsers.add_parser("replay", help="Replay a recorded run.", parents=[json_parent])
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
    eval_p = subparsers.add_parser("evaluate", help="Evaluate assertions for a recorded run.")
    eval_p.add_argument("run_id", help="Run identifier.")
    eval_p.add_argument("--scenario", help="Optional explicit path to scenario JSON file.")
    eval_p.add_argument("--output", "-o", help="Recording output directory.", default=".recordings")
    eval_p.set_defaults(func=cmd_evaluate)

    # trace subcommand (framework-agnostic external agent traces)
    trace_p = subparsers.add_parser(
        "trace", help="Evaluate externally produced agent traces.", parents=[json_parent]
    )
    trace_sub = trace_p.add_subparsers(dest="trace_command", required=True)
    trace_eval = trace_sub.add_parser(
        "evaluate",
        help="Re-execute a tool-call trace in the simulated environment and score it.",
        parents=[json_parent],
    )
    trace_eval.add_argument("trace", help="Path to a trace JSON file (tool_calls or openai_chat).")
    trace_eval.set_defaults(func=cmd_trace_evaluate)

    # evaluator subcommand (evaluation of the evaluator)
    evaluator_p = subparsers.add_parser(
        "evaluator", help="Measure the trajectory evaluator itself.", parents=[json_parent]
    )
    evaluator_sub = evaluator_p.add_subparsers(dest="evaluator_command", required=True)
    evaluator_val = evaluator_sub.add_parser(
        "validate",
        help="Measure evaluator FP/FN rates on construction-labelled perturbed trajectories.",
    )
    evaluator_val.add_argument("--output", "-o", required=True, help="Report output directory.")
    evaluator_val.add_argument("--benchmark", default="benchmark-v1", help="Built-in benchmark id.")
    evaluator_val.set_defaults(func=cmd_evaluator_validate)

    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    is_json_flag = "--json" in raw_argv

    args = parser.parse_args(argv)
    if is_json_flag:
        args.json = True

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return 2
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())

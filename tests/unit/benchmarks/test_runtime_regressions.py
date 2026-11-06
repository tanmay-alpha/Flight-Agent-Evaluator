"""Consumer-visible regressions for benchmark execution and artifact provenance."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.agent.baselines import NoOpBaselineAgent, ScriptedOracleAgent
from flight_agent_evaluator.benchmarks.consistency import ResultBundleConsistencyVerifier
from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkManifestLoader,
    ManifestValidationError,
)
from flight_agent_evaluator.benchmarks.registry import BenchmarkAgentRegistry
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkInvocation,
    render_reproduction_command,
)
from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    ModelProvenance,
    ModelUsage,
)
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.recording.journal import HashChainJournal


def _case() -> Any:
    return BenchmarkManifestLoader().load_manifest("builtin:benchmark-v1")[1][0]


class InspectingAgent:
    agent_id = "inspector"
    agent_version = "1.0.0"
    configuration_digest = "a" * 64

    def __init__(self) -> None:
        self.observed: list[tuple[int, int, str]] = []

    async def execute(self, task: Any, executor: Any, state: Any, context: Any) -> AgentRunResult:
        self.observed.append(
            (task.max_turns, context.seed, str(context.id_factory.next("probe", 0)))
        )
        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            stop_reason=AgentStopReason.COMPLETED,
            final_response="done",
            usage=ModelUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            model_latency_ms=13.0,
            model_provenance=ModelProvenance(
                provider_label="test",
                model_id="test-model",
                model_configuration_digest=self.configuration_digest,
                prompt_policy_id="test-prompt",
                prompt_digest="c" * 64,
                tool_schema_digest="d" * 64,
            ),
        )


def test_execution_seed_changes_runtime_ids_deterministically() -> None:
    runner, agent, case = BenchmarkRunner(), InspectingAgent(), _case()
    for seed in (101, 102, 101):
        asyncio.run(runner.run_case(case, agent, execution_seed=seed))
    assert agent.observed[0] == agent.observed[2]
    assert agent.observed[0][2] != agent.observed[1][2]


def test_configuration_digest_and_turn_limit_bind_execution_identity() -> None:
    runner, agent, case = BenchmarkRunner(), InspectingAgent(), _case()
    first = asyncio.run(runner.run_case(case, agent))
    agent.configuration_digest = "b" * 64
    second = asyncio.run(runner.run_case(case, agent))
    assert first.run_id != second.run_id
    limited = replace(
        case,
        scenario=case.scenario.model_copy(
            update={"limits": case.scenario.limits.model_copy(update={"max_turns": 2})}
        ),
    )
    third = asyncio.run(runner.run_case(limited, agent))
    assert agent.observed[-1][0] == 2
    assert third.run_id != second.run_id
    assert third.usage.total_tokens == 5
    assert third.model_latency_ms == 13.0
    assert third.model_provenance.model_id == "test-model"
    assert (
        third.compute_semantic_result_digest()
        == third.model_copy(
            update={"model_latency_ms": 999.0, "wall_time_ms": 999.0}
        ).compute_semantic_result_digest()
    )


class ExplodingAgent(NoOpBaselineAgent):
    async def execute(self, *args: Any, **kwargs: Any) -> AgentRunResult:
        raise RuntimeError("password=private-value Bearer secret-value")


def test_agent_exception_is_recorded_and_journal_closed(tmp_path: Path) -> None:
    loaded = ScenarioLoader().load_from_path(Path("resources/scenarios/lax-sfo-ontime.json"))
    result = asyncio.run(
        BenchmarkRunner().run_scenario(
            loaded.scenario,
            ExplodingAgent(),
            output_dir=tmp_path,
            scenario_source_digest=loaded.digest,
        )
    )
    assert result.stop_reason == AgentStopReason.ERROR
    assert not result.task_success
    assert "AGENT.EXECUTION_ERROR" in result.failure_codes
    assert result.failure_details
    journal = HashChainJournal.read_unverified_jsonl(next(tmp_path.glob("*.jsonl")))
    assert journal.entries[-1].type == "run_completed"
    assert "private-value" not in journal.to_jsonl_string()
    assert "secret-value" not in result.model_dump_json()


@pytest.mark.parametrize("exception", [asyncio.CancelledError, KeyboardInterrupt])
def test_agent_control_flow_exceptions_propagate(exception: type[BaseException]) -> None:
    class Interrupted(ExplodingAgent):
        async def execute(self, *args: Any, **kwargs: Any) -> AgentRunResult:
            raise exception()

    with pytest.raises(exception):
        asyncio.run(BenchmarkRunner().run_case(_case(), Interrupted()))


def test_one_exploding_agent_keeps_complete_verified_bundle(tmp_path: Path) -> None:
    registry = BenchmarkAgentRegistry()
    registry.register(
        "no-op-baseline",
        ExplodingAgent,
        implementation="flight_agent_evaluator.agent.baselines.NoOpBaselineAgent",
    )
    artifact = CanonicalBenchmarkEngine(registry=registry).run_benchmark(
        agent_ids=["no-op-baseline", "scripted-oracle"],
        scenario_filter=["lax-sfo-ontime"],
        output_dir=tmp_path,
    )
    assert len(artifact.case_results) == 2
    assert artifact.case_results[0].stop_reason == AgentStopReason.ERROR
    assert artifact.case_results[1].stop_reason == AgentStopReason.COMPLETED
    assert ResultBundleConsistencyVerifier().verify_bundle(tmp_path).valid


def test_missing_expectation_requires_explicit_development_opt_in() -> None:
    case = _case()
    scenario = case.scenario.model_copy(
        update={
            "scenario_id": case.scenario.scenario_id.model_copy(
                update={"id": "unpublished-scenario"}
            )
        }
    )
    with pytest.raises((FileNotFoundError, ValueError)):
        asyncio.run(BenchmarkRunner().run_scenario(scenario, NoOpBaselineAgent()))
    result = asyncio.run(
        BenchmarkRunner().run_scenario(
            scenario,
            NoOpBaselineAgent(),
            allow_development_expectation=True,
        )
    )
    assert not result.task_success


def test_scenario_mode_is_closed_and_max_turns_defaults() -> None:
    data = _case().scenario.model_dump(mode="json")
    data["scenario_mode"] = "transactonal"
    with pytest.raises(ValidationError):
        BenchmarkScenario.model_validate(data)
    assert _case().scenario.limits.max_turns == 10


def test_reproduction_command_retains_model_flags_and_output() -> None:
    invocation = BenchmarkInvocation(
        manifest_reference="builtin:benchmark-v1",
        agent_ids=["model"],
        output_dir="custom-output",
        model_options={
            "model": "different-model",
            "model-mode": "live",
            "allow-live-model": True,
        },
    )
    command = render_reproduction_command(invocation)
    assert command is not None
    assert "--model different-model" in command
    assert "--model-mode live" in command
    assert "--allow-live-model" in command
    assert command.endswith("--output custom-output")
    assert (
        render_reproduction_command(
            invocation.model_copy(
                update={
                    "model_options": {"model": "different-model", "model-mode": "replay"},
                }
            )
        )
        is None
    )


def test_manifest_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    manifest = Path("resources/benchmarks/benchmark-v1.json").read_text(encoding="utf-8")
    data = json.loads(manifest)
    duplicate = manifest.replace("{", '{"benchmark_id":"ignored",', 1)
    path = tmp_path / "duplicate.json"
    path.write_text(duplicate, encoding="utf-8")
    assert data["benchmark_id"]
    with pytest.raises(ManifestValidationError, match="Duplicate|duplicate"):
        BenchmarkManifestLoader().load_manifest(path)


def test_failure_details_come_from_diagnostics_without_pseudo_codes() -> None:
    result = asyncio.run(BenchmarkRunner().run_case(_case(), NoOpBaselineAgent()))
    assert result.failure_details
    assert {detail.code for detail in result.failure_details} == set(result.failure_codes)
    assert "safety_violation" not in result.failure_codes
    assert all(detail.message and detail.severity for detail in result.failure_details)
    assert result.schema_version == "0.4.0"


def test_benchmark_time_limit_is_enforced(tmp_path: Path) -> None:
    from flight_agent_evaluator.contracts.faults import ActivationRule, DelayedResponseFault
    from flight_agent_evaluator.recording.contracts import ScriptedTrajectory

    loaded = ScenarioLoader().load_from_path(Path("resources/scenarios/lax-sfo-ontime.json"))
    scenario = loaded.scenario
    first = scenario.trajectory.steps[0].model_dump(mode="json")
    trajectory = ScriptedTrajectory.model_validate(
        {
            "trajectory_id": "slow",
            "description": "slow tools",
            "steps": [
                first,
                {**first, "step_id": "again"},
                {"kind": "produce_final_response", "step_id": "final", "response": "done"},
            ],
        }
    )
    scenario = scenario.model_copy(
        update={
            "trajectory": trajectory,
            "faults": (
                DelayedResponseFault(
                    target_provider="synthetic-fixture",
                    target_tool="flight.get_status",
                    activation=ActivationRule(kind="always"),
                    occurrence_count=1,
                    delay_seconds=120,
                ),
            ),
            "limits": scenario.limits.model_copy(update={"time_limit_seconds": 60}),
        }
    )
    asyncio.run(
        BenchmarkRunner().run_scenario(
            scenario,
            ScriptedOracleAgent(),
            expectation=_case().expectation,
            output_dir=tmp_path,
            scenario_source_digest=loaded.digest,
        )
    )
    journal = HashChainJournal.read_unverified_jsonl(next(tmp_path.glob("*.jsonl")))
    results = [entry.payload for entry in journal.entries if entry.type == "tool_result"]
    assert results[1]["error"]["error_type"] == "time_limit_exceeded"


def test_case_boundary_records_failure_and_continues(tmp_path: Path) -> None:
    class BrokenRunner(BenchmarkRunner):
        async def run_case(self, case: Any, agent: Any, *args: Any, **kwargs: Any) -> Any:
            if case.scenario.scenario_id.id == "jfk-lhr-delay":
                raise RuntimeError("private-provider-payload")
            return await super().run_case(case, agent, *args, **kwargs)

    artifact = CanonicalBenchmarkEngine(runner=BrokenRunner()).run_benchmark(
        agent_ids=["no-op-baseline"],
        scenario_filter=["jfk-lhr-delay", "lax-sfo-ontime"],
        output_dir=tmp_path,
    )
    assert artifact.total_runs == 2
    assert artifact.case_results[0].evaluator_status == "execution_error"
    assert "AGENT.EXECUTION_ERROR" in artifact.case_results[0].failure_codes
    assert "private-provider-payload" not in (tmp_path / "run.json").read_text(encoding="utf-8")


def test_model_configuration_changes_suite_identity_and_records_mode(tmp_path: Path) -> None:
    from flight_agent_evaluator.agent.model_client import ModelAgentSettings

    artifacts = []
    for digest in ("a" * 64, "b" * 64):
        registry = BenchmarkAgentRegistry(ModelAgentSettings(mode="live", allow_live_model=True))
        agent = InspectingAgent()
        agent.agent_id = "model"
        agent.configuration_digest = digest

        def factory(agent: InspectingAgent = agent) -> InspectingAgent:
            return agent

        registry.register(
            "model",
            factory,
            implementation="flight_agent_evaluator.agent.loop.ModelToolCallingAgent",
        )
        artifact = CanonicalBenchmarkEngine(registry=registry).run_benchmark(
            agent_ids=["model"],
            scenario_filter=["lax-sfo-ontime"],
            output_dir=tmp_path / digest[:1],
        )
        artifacts.append(artifact)
        assert artifact.execution_mode == "model-live"
        assert artifact.run_policy["network_allowed"] is True
        assert artifact.agent_provenance[0].configuration_digest == digest
        assert artifact.case_results[0].usage.total_tokens == 5
    assert artifacts[0].run_semantic_id != artifacts[1].run_semantic_id
    assert artifacts[0].case_results[0].run_id != artifacts[1].case_results[0].run_id


@pytest.mark.parametrize("filename", ["run.json", "summary.json"])
def test_bundle_parser_rejects_duplicate_keys(tmp_path: Path, filename: str) -> None:
    CanonicalBenchmarkEngine().run_benchmark(
        agent_ids=["no-op-baseline"],
        scenario_filter=["lax-sfo-ontime"],
        output_dir=tmp_path,
    )
    path = tmp_path / filename
    text = path.read_text(encoding="utf-8")
    key = "run_semantic_id" if filename == "run.json" else "total_cases"
    value = json.loads(text)[key]
    path.write_text(
        text.replace("{", "{" + json.dumps(key) + ":" + json.dumps(value) + ",", 1),
        encoding="utf-8",
    )
    report = ResultBundleConsistencyVerifier().verify_bundle(tmp_path)
    assert not report.valid
    assert not next(
        item for item in report.checks if item.check_id == "BND-02-SCHEMA-VALIDATION"
    ).passed


def test_release_fixture_parser_rejects_duplicate_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from flight_agent_evaluator.benchmarks import release_verifier

    class DuplicateFixtureLocator:
        def read_bytes(self, _: Any) -> bytes:
            return b'{"data": 1, "data": 2}'

    monkeypatch.setattr(release_verifier, "get_builtin_locator", DuplicateFixtureLocator)
    report = release_verifier.ReleaseVerifier().verify_installed_release()
    assert not next(item for item in report.checks if item.check_id == "REL-06-FIXTURE-DATA").passed


def test_multiple_seeds_persist_every_case_without_overwriting(tmp_path: Path) -> None:
    class SeedLoader(BenchmarkManifestLoader):
        def load_manifest(self, *args: Any, **kwargs: Any) -> Any:
            manifest, cases = super().load_manifest(*args, **kwargs)
            manifest = manifest.model_copy(
                update={
                    "run_policy": manifest.run_policy.model_copy(update={"seeds": (41, 42)}),
                }
            )
            digest = manifest.compute_canonical_digest()
            manifest = manifest.model_copy(update={"manifest_digest": digest})
            return manifest, [replace(case, manifest_digest=digest) for case in cases]

    loader = SeedLoader()
    artifact = CanonicalBenchmarkEngine(loader=loader).run_benchmark(
        agent_ids=["no-op-baseline"],
        scenario_filter=["lax-sfo-ontime"],
    )
    artifact.persist_verified_bundle(tmp_path)
    assert len(list((tmp_path / "cases").glob("*.json"))) == 2
    assert ResultBundleConsistencyVerifier(loader=loader).verify_bundle(tmp_path).valid


def test_bundle_parity_excludes_model_and_wall_latency(tmp_path: Path) -> None:
    CanonicalBenchmarkEngine().run_benchmark(
        agent_ids=["no-op-baseline"],
        scenario_filter=["lax-sfo-ontime"],
        output_dir=tmp_path,
    )
    path = next((tmp_path / "cases").glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(model_latency_ms=999.0, wall_time_ms=999.0)
    path.write_text(json.dumps(data), encoding="utf-8")
    assert ResultBundleConsistencyVerifier().verify_bundle(tmp_path).valid

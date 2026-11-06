"""Runner regressions: default provider, scenario limits, allowlist source, call ids."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from flight_agent_evaluator.cli.main import main as cli_main
from flight_agent_evaluator.contracts.faults import ActivationRule, DelayedResponseFault
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.state import StateProjector
from flight_agent_evaluator.recording.contracts import JournalEntry, ScriptedTrajectory
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import (
    build_readonly_registry,
    build_transactional_registry,
    default_allowed_tools,
)

SCENARIOS = Path("resources/scenarios")


def _load(name: str) -> BenchmarkScenario:
    return ScenarioLoader().load_from_path(SCENARIOS / name).scenario


def _run(scenario: BenchmarkScenario, tmp_path: Path, driver: Any = None) -> list[JournalEntry]:
    recording = asyncio.run(ScenarioRunner().run(scenario, output_dir=tmp_path, driver=driver))
    return list(FileRecordingStore(tmp_path).read_recording(str(recording.run_id)).entries)


def _results(entries: list[JournalEntry]) -> list[dict[str, Any]]:
    return [dict(e.payload) for e in entries if e.type == "tool_result"]


def test_runner_without_provider_executes_tools(tmp_path: Path) -> None:
    results = _results(_run(_load("lax-sfo-ontime.json"), tmp_path))
    assert results
    assert all(r["status"] == "success" for r in results), results


def test_cli_run_journal_contains_successful_tool_results(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert cli_main(["run", str(SCENARIOS / "lax-sfo-ontime.json"), "-o", str(out)]) == 0
    journals = list(out.glob("*.jsonl"))
    assert len(journals) == 1
    text = journals[0].read_text(encoding="utf-8")
    assert "No provider configured" not in text
    entries = HashChainJournal.read_unverified_jsonl(journals[0]).entries
    results = _results(list(entries))
    assert results
    assert all(r["status"] == "success" for r in results)


def _time_limited_scenario() -> BenchmarkScenario:
    scenario = _load("lax-sfo-ontime.json")
    status_step = scenario.trajectory.steps[0].model_dump(mode="json")
    trajectory = ScriptedTrajectory.model_validate(
        {
            "trajectory_id": "time-limit",
            "description": "two status lookups across a slow provider response",
            "steps": [
                status_step,
                {**status_step, "step_id": "step-again"},
                {"kind": "produce_final_response", "step_id": "final", "response": "done"},
            ],
        }
    )
    fault = DelayedResponseFault(
        target_provider="synthetic-fixture",
        target_tool="flight.get_status",
        activation=ActivationRule(kind="always"),
        occurrence_count=1,
        delay_seconds=120,
    )
    return scenario.model_copy(
        update={
            "trajectory": trajectory,
            "faults": (fault,),
            "limits": scenario.limits.model_copy(update={"time_limit_seconds": 60}),
        }
    )


def test_runner_enforces_scenario_time_limit_and_journals_result(tmp_path: Path) -> None:
    entries = _run(_time_limited_scenario(), tmp_path)
    calls = [e.payload["call_id"] for e in entries if e.type == "tool_call"]
    results = _results(entries)
    # Every journaled call has exactly one terminal result.
    assert sorted(calls) == sorted(r["call_id"] for r in results)
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "failure"
    assert results[1]["error"]["error_type"] == "time_limit_exceeded"


@dataclass
class _Outcome:
    tool_calls_made: int
    final_response: str | None
    checkpoints: tuple[str, ...]


class _OffScriptDriver:
    """Calls a registered tool that the golden trajectory never uses."""

    agent_id = "off-script"

    def __init__(self) -> None:
        self.results: list[Any] = []

    async def execute(self, *, executor: Any, context: RunContext, **_: Any) -> _Outcome:
        call = ToolCall(
            call_id=uuid.uuid5(uuid.NAMESPACE_URL, "off-script"),
            run_id=context.run_id,
            tool_name="flight.search_flights",
            arguments={"origin": "LAX", "destination": "SFO", "departure_date": "2026-07-28"},
            start_time=context.clock.now(),
        )
        self.results.append(await executor.execute(tool_call=call, context=context))
        return _Outcome(tool_calls_made=1, final_response="done", checkpoints=())


def test_allowlist_is_not_derived_from_golden_trajectory(tmp_path: Path) -> None:
    driver = _OffScriptDriver()
    _run(_load("lax-sfo-ontime.json"), tmp_path, driver=driver)
    error = driver.results[0].error
    assert error is None or error.error_type != "authorization_error"


def test_explicit_allowed_tools_restrict_execution(tmp_path: Path) -> None:
    scenario = _load("lax-sfo-ontime.json").model_copy(
        update={"allowed_tools": ("flight.get_status",)}
    )
    driver = _OffScriptDriver()
    _run(scenario, tmp_path, driver=driver)
    assert driver.results[0].error.error_type == "authorization_error"


def test_default_allowed_tools_follow_scenario_mode() -> None:
    read_only = _load("lax-sfo-ontime.json")
    transactional = _load("transactional/mutation-without-approval.json")
    assert default_allowed_tools(read_only) == list(build_readonly_registry().tool_names())
    assert default_allowed_tools(transactional) == list(build_transactional_registry().tool_names())
    # The golden trajectory of mutation-without-approval never confirms; the
    # allowlist still contains every transactional tool.
    assert "booking.confirm_rebooking" in default_allowed_tools(transactional)


def test_default_allowed_tools_rejects_unregistered_names() -> None:
    scenario = _load("lax-sfo-ontime.json").model_copy(
        update={"allowed_tools": ("booking.confirm_rebooking",)}
    )
    with pytest.raises(ValueError, match="not registered"):
        default_allowed_tools(scenario)


def test_failed_call_and_retry_have_distinct_call_ids(tmp_path: Path) -> None:
    entries = _run(_load("jfk-lhr-timeout-recovery.json"), tmp_path)
    call_ids = [e.payload["call_id"] for e in entries if e.type == "tool_call"]
    assert len(call_ids) == len(set(call_ids))
    projector = StateProjector()
    state = projector.project_journal(HashChainJournal())
    for entry in entries:
        state = projector.project_entry(state, entry.type, dict(entry.payload))
    statuses = [tc["status"] for tc in state.data["tool_calls"]]
    assert statuses == ["timeout", "success", "success"]


def test_state_projector_resolves_results_to_pending_calls() -> None:
    projector = StateProjector()
    state = projector.project_journal(HashChainJournal())
    for payload in (
        {"call_id": "dup", "tool_name": "flight.get_status"},
        {"call_id": "dup", "tool_name": "flight.get_status"},
    ):
        state = projector.project_entry(state, "tool_call", payload)
    state = projector.project_entry(state, "tool_result", {"call_id": "dup", "status": "timeout"})
    state = projector.project_entry(
        state, "tool_result", {"call_id": "dup", "status": "success", "result": {"ok": 1}}
    )
    calls = state.data["tool_calls"]
    assert [c["status"] for c in calls] == ["timeout", "success"]
    assert calls[1]["result"] == {"ok": 1}


def test_driver_exception_does_not_persist_secret_text(tmp_path: Path) -> None:
    class SecretFailure:
        async def execute(self, **_: Any) -> Any:
            raise RuntimeError("password=private-value")

    entries = _run(_load("lax-sfo-ontime.json"), tmp_path, driver=SecretFailure())
    assert entries[-1].type == "run_completed"
    assert entries[-1].payload["run_status"] == "error"
    assert "private-value" not in "".join(entry.model_dump_json() for entry in entries)

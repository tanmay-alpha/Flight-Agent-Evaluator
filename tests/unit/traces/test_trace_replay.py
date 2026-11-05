"""TraceReplayPolicy and evaluate_trace: environment re-execution, divergence, examples."""

from __future__ import annotations

import asyncio
import copy
import datetime
import json
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

import flight_agent_evaluator
from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.contracts.model import AgentStopReason, AgentTask
from flight_agent_evaluator.contracts.tools import ToolCall, ToolError, ToolResult
from flight_agent_evaluator.engine import benchmark
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.traces import (
    TraceReplayPolicy,
    TraceResolutionError,
    evaluate as trace_evaluate,
    evaluate_trace,
    load_trace,
    parse_trace,
)

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "traces"
CORRECT_EXAMPLE = EXAMPLES / "jfk-lhr-delay.correct.json"
UNSAFE_EXAMPLE = EXAMPLES / "approval-denied.unsafe.json"
RESOURCES = Path(flight_agent_evaluator.__file__).resolve().parent / "resources"
T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def _doc(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


class _CapturingJournal(HashChainJournal):
    instances: list[HashChainJournal] = []

    def __init__(self) -> None:
        super().__init__()
        _CapturingJournal.instances.append(self)


@pytest.fixture
def captured_journals(monkeypatch: pytest.MonkeyPatch) -> list[HashChainJournal]:
    _CapturingJournal.instances = []
    monkeypatch.setattr(benchmark, "HashChainJournal", _CapturingJournal)
    return _CapturingJournal.instances


# ---------------------------------------------------------------------------
# Policy unit tests against a scripted executor
# ---------------------------------------------------------------------------


class _ScriptedExecutor:
    """Returns pre-set ToolResults in order and records submitted calls."""

    def __init__(self, outcomes: list[tuple[str, Any]]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[ToolCall] = []

    async def execute(self, tool_call: ToolCall, *, context: RunContext) -> ToolResult:
        self.calls.append(tool_call)
        status, value = self._outcomes.pop(0)
        if status == "success":
            return ToolResult(
                call_id=tool_call.call_id, status="success", result=value, end_time=T0
            )
        return ToolResult(
            call_id=tool_call.call_id,
            status="failure",
            error=ToolError(error_type="authorization_error", message=str(value)),
            end_time=T0,
        )


def _context() -> RunContext:
    return RunContext(
        run_id=uuid.UUID(int=1),
        scenario_id="unit",
        scenario_version=1,
        seed=1,
        clock=DeterministicVirtualClock(T0),
        id_factory=DeterministicIdFactory(scenario_id="unit", scenario_version=1, seed=1),
        tool_call_limit=10,
        time_limit_seconds=60,
        correlation_id="corr",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


def _run_policy(calls: list[dict[str, Any]], outcomes: list[tuple[str, Any]], **extra: Any):
    trace = parse_trace(
        {
            "schema_version": "1.0",
            "scenario": {"builtin": "unit"},
            "agent": {"name": "unit-agent"},
            "calls": calls,
            "final_response": "agent says done",
            **extra,
        }
    )
    policy = TraceReplayPolicy(trace)
    executor = _ScriptedExecutor(outcomes)
    task = AgentTask(task_id="t", scenario_id="unit", public_request="r")
    result = asyncio.run(
        policy.execute(task, cast(ToolExecutor, executor), StateSnapshot(), _context())
    )
    return policy, executor, result


def test_policy_satisfies_agent_protocol() -> None:
    trace = parse_trace(
        {"schema_version": "1.0", "scenario": {"builtin": "x"}, "agent": {"name": "a"}}
    )
    policy = TraceReplayPolicy(trace)
    assert isinstance(policy, AgentPolicy)
    assert policy.agent_id == "trace:a"
    assert policy.agent_version == "unversioned"


def test_policy_submits_calls_in_order_without_trusting_mutation_class() -> None:
    _, executor, result = _run_policy(
        [{"tool_name": "a.one", "arguments": {"x": 1}}, {"tool_name": "b__two"}],
        [("success", {"ok": 1}), ("failure", "denied")],
        usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "model_calls": 4},
    )
    assert [c.tool_name for c in executor.calls] == ["a.one", "b.two"]
    assert executor.calls[0].arguments == {"x": 1}
    assert all(c.mutation_class is None for c in executor.calls)
    assert len({c.call_id for c in executor.calls}) == 2
    assert result.stop_reason == AgentStopReason.COMPLETED
    assert result.final_response == "agent says done"
    assert result.tool_call_count == 2
    assert result.model_call_count == 4
    assert result.usage.total_tokens == 3
    assert result.warnings == []


def test_policy_resolves_ref_step_against_environment_results() -> None:
    _, executor, _ = _run_policy(
        [
            {
                "tool_name": "booking.hold_alternative",
                "observed_result": {"hold_id": "agent-claim"},
            },
            {
                "tool_name": "booking.release_hold",
                "arguments": {
                    "hold_id": {"$ref_step": 0, "json_pointer": "/hold_id"},
                    "inline": "$ref:0/hold_id",
                },
            },
        ],
        [("success", {"hold_id": "env-hold"}), ("success", {"status": "released"})],
    )
    assert executor.calls[1].arguments == {"hold_id": "env-hold", "inline": "env-hold"}


def test_policy_wraps_non_dict_results_for_refs() -> None:
    _, executor, result = _run_policy(
        [
            {"tool_name": "a.list", "observed_result": [1, 2]},
            {"tool_name": "a.use", "arguments": {"first": "$ref:0/result/0"}},
        ],
        [("success", [1, 2]), ("success", None)],
    )
    assert executor.calls[1].arguments == {"first": 1}
    assert result.warnings == []


def test_policy_stops_on_unresolvable_ref_and_keeps_agent_claim() -> None:
    policy, executor, result = _run_policy(
        [
            {"tool_name": "a.fail"},
            {"tool_name": "a.use", "arguments": {"h": {"$ref_step": 0, "json_pointer": "/x"}}},
            {"tool_name": "a.after"},
        ],
        [("failure", "boom")],
    )
    assert len(executor.calls) == 1
    assert result.stop_reason == AgentStopReason.ERROR
    assert result.tool_call_count == 1
    assert result.final_response == "agent says done"
    kinds = [(d.call_index, d.kind) for d in policy.divergences]
    assert kinds == [(1, "not_replayed"), (2, "not_replayed")]
    assert "Cannot reference failed step 0" in policy.divergences[0].detail
    assert policy.divergences[1].detail == "replay stopped earlier"
    assert len(result.warnings) == 2


@pytest.mark.parametrize(
    ("call", "outcome", "kind"),
    [
        ({"observed_result": {"a": 1}}, ("success", {"a": 1}), None),
        ({"observed_result": {"a": 1.0}}, ("success", {"a": 1}), None),
        ({"observed_result": {"a": 2}}, ("success", {"a": 1}), "result_mismatch"),
        ({"observed_result": {"a": 1}}, ("failure", "denied"), "status_mismatch"),
        ({"observed_error": "denied"}, ("failure", "denied"), None),
        ({"observed_error": "denied"}, ("success", {"a": 1}), "status_mismatch"),
        ({}, ("failure", "denied"), None),
        ({"observed_result": "x"}, ("success", {1, 2}), "result_mismatch"),
    ],
)
def test_policy_divergence_detection(
    call: dict[str, Any], outcome: tuple[str, Any], kind: str | None
) -> None:
    policy, _, result = _run_policy([{"tool_name": "a.b", **call}], [outcome])
    found = [d.kind for d in policy.divergences]
    assert found == ([kind] if kind else [])
    assert len(result.warnings) == len(found)
    if kind:
        assert result.warnings[0].startswith(f"trace_divergence[{kind}] call 0 (a.b)")


# ---------------------------------------------------------------------------
# End-to-end through BenchmarkRunner.run_scenario
# ---------------------------------------------------------------------------


def test_correct_example_passes() -> None:
    report = evaluate_trace(load_trace(CORRECT_EXAMPLE))
    assert report.scenario_id == "jfk-lhr-delay"
    assert report.scenario_source == "builtin:scenarios/jfk-lhr-delay.json"
    assert report.expectation_source == "builtin:expectations/jfk-lhr-delay.json"
    assert report.metrics.task_success is True
    assert report.metrics.safety_pass is True
    assert report.metrics.failure_codes == []
    assert report.metrics.agent_id == "trace:hand-written-example"
    assert report.replayed_call_count == report.trace_call_count == 2
    assert report.trace_consistent is True
    assert report.divergences == []


def test_journal_is_produced_by_environment_not_agent_claims(
    captured_journals: list[HashChainJournal],
) -> None:
    doc = _doc(CORRECT_EXAMPLE)
    fabricated = {"status": {"operational_status": "FABRICATED_BY_AGENT", "delay_minutes": 0}}
    doc["calls"][0]["observed_result"] = fabricated
    doc["calls"][1]["observed_result"] = {"offers": []}

    report = evaluate_trace(parse_trace(doc))

    (journal,) = captured_journals
    assert journal.verify()
    tool_results = [e.payload for e in journal.entries if e.type == "tool_result"]
    assert len(tool_results) == 2
    assert all(p["status"] == "success" for p in tool_results)
    assert tool_results[0]["result"]["status"]["operational_status"] == "delayed"
    assert tool_results[0]["result"]["status"]["delay_minutes"] == 105
    assert tool_results[1]["result"]["offers"] != []
    serialized = journal.to_jsonl_string()
    assert "FABRICATED_BY_AGENT" not in serialized
    tool_calls = [e.payload for e in journal.entries if e.type == "tool_call"]
    assert [p["tool_name"] for p in tool_calls] == ["flight.get_status", "flight.search_flights"]
    assert all(p["mutation_class"] == "read_only" for p in tool_calls)

    assert [(d.call_index, d.kind) for d in report.divergences] == [
        (0, "result_mismatch"),
        (1, "result_mismatch"),
    ]
    assert report.trace_consistent is False


def test_agent_claims_do_not_change_scores_or_journal_digest() -> None:
    consistent = evaluate_trace(load_trace(CORRECT_EXAMPLE))
    doc = _doc(CORRECT_EXAMPLE)
    doc["calls"][0]["observed_result"] = {"status": "cancelled"}
    lying = evaluate_trace(parse_trace(doc))
    for call in doc["calls"]:
        call.pop("observed_result", None)
    silent = evaluate_trace(parse_trace(doc))

    assert lying.trace_consistent is False and silent.trace_consistent is True
    assert lying.metrics == consistent.metrics == silent.metrics


def test_unsafe_example_pipeline_mechanics(captured_journals: list[HashChainJournal]) -> None:
    """Only pipeline mechanics: whether it is flagged is the evaluator's job (EvalSafety)."""
    report = evaluate_trace(load_trace(UNSAFE_EXAMPLE))

    assert report.scenario_id == "approval-denied"
    assert report.scenario_source == "builtin:scenarios/transactional/approval-denied.json"
    assert report.expectation_source == "builtin:expectations/transactional/approval-denied.json"
    assert report.replayed_call_count == report.trace_call_count == 4

    (journal,) = captured_journals
    calls = [e.payload for e in journal.entries if e.type == "tool_call"]
    results = [e.payload for e in journal.entries if e.type == "tool_result"]
    assert [c["tool_name"] for c in calls] == [
        "booking.get_current",
        "booking.hold_alternative",
        "approval.request",
        "booking.confirm_rebooking",
    ]
    assert calls[3]["mutation_class"] == "sensitive_simulated_mutation"
    assert results[2]["result"]["status"] == "denied"
    assert results[3]["status"] != "success"
    final = [e.payload for e in journal.entries if e.type == "final_response"]
    assert final[0]["response"].endswith("is confirmed.")

    # Calls 1-2 match the environment; the fabricated confirmation on call 3 does not.
    assert [(d.call_index, d.tool_name) for d in report.divergences] == [
        (3, "booking.confirm_rebooking")
    ]
    assert report.trace_consistent is False


# ---------------------------------------------------------------------------
# Scenario / expectation resolution
# ---------------------------------------------------------------------------


def _path_trace(scenario: dict[str, Any]) -> Any:
    doc = _doc(CORRECT_EXAMPLE)
    doc["scenario"] = scenario
    return parse_trace(doc)


def test_path_scenario_with_explicit_expectation(tmp_path: Path) -> None:
    report = evaluate_trace(
        _path_trace(
            {
                "path": str(RESOURCES / "scenarios" / "jfk-lhr-delay.json"),
                "expectation_path": str(RESOURCES / "expectations" / "jfk-lhr-delay.json"),
            }
        ),
        base_dir=tmp_path,
    )
    assert report.metrics.task_success is True
    assert report.expectation_source.endswith("jfk-lhr-delay.json")
    assert not report.expectation_source.startswith("builtin:")


def test_relative_path_scenario_uses_builtin_expectation_by_id(tmp_path: Path) -> None:
    scenario_file = tmp_path / "copy.json"
    scenario_file.write_bytes((RESOURCES / "scenarios" / "jfk-lhr-delay.json").read_bytes())
    report = evaluate_trace(_path_trace({"path": "copy.json"}), base_dir=tmp_path)
    assert report.scenario_source == str(scenario_file.resolve())
    assert report.expectation_source == "builtin:expectations/jfk-lhr-delay.json"
    assert report.metrics.task_success is True


def test_path_scenario_without_authored_expectation_is_rejected(tmp_path: Path) -> None:
    data = json.loads((RESOURCES / "scenarios" / "jfk-lhr-delay.json").read_text("utf-8"))
    data["scenario_id"]["id"] = "custom-unscored"
    (tmp_path / "custom.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TraceResolutionError, match="no authored expectation"):
        evaluate_trace(_path_trace({"path": "custom.json"}), base_dir=tmp_path)


def test_unknown_builtin_scenario_is_rejected() -> None:
    with pytest.raises(TraceResolutionError, match="Unknown built-in scenario"):
        evaluate_trace(_path_trace({"builtin": "no-such-scenario"}))


def test_builtin_without_expectation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    real = trace_evaluate._builtin_exists
    monkeypatch.setattr(
        trace_evaluate,
        "_builtin_exists",
        lambda path, kind: real(path, kind) and not path.startswith("expectations/"),
    )
    with pytest.raises(TraceResolutionError, match="has no authored expectation"):
        evaluate_trace(load_trace(CORRECT_EXAMPLE))


def test_examples_are_marked_hand_written() -> None:
    for path in (CORRECT_EXAMPLE, UNSAFE_EXAMPLE):
        trace = load_trace(path)
        assert trace.notes is not None
        assert trace.notes.startswith("HAND-WRITTEN EXAMPLE, NOT MODEL OUTPUT.")
        assert trace.usage is None and trace.agent.model is None


def test_evaluation_is_deterministic() -> None:
    trace = load_trace(UNSAFE_EXAMPLE)
    first = evaluate_trace(trace)
    second = evaluate_trace(copy.deepcopy(trace))
    assert first.divergences == second.divergences
    assert first.metrics.journal_digest == second.metrics.journal_digest

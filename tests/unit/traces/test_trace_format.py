"""Validation and normalisation tests for the imported trace formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flight_agent_evaluator.traces import format as trace_format
from flight_agent_evaluator.traces.format import (
    TraceFormatError,
    _provider_to_internal_tool_name,
    load_trace,
    parse_trace,
)


def _native(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "scenario": {"builtin": "jfk-lhr-delay"},
        "agent": {"name": "agent-x", "model": "m", "framework": "f"},
        "calls": [
            {
                "tool_name": "flight.get_status",
                "arguments": {"flight_id": "AS142", "operating_day": "2026-07-28"},
            }
        ],
        "final_response": "done",
    }
    doc.update(overrides)
    return doc


def _chat(messages: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "format": "openai_chat",
        "scenario": {"builtin": "jfk-lhr-delay"},
        "agent": {"name": "agent-x"},
        "messages": messages,
    }
    doc.update(overrides)
    return doc


def _assistant_call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
        ],
    }


# ---------------------------------------------------------------------------
# Native format validation
# ---------------------------------------------------------------------------


def test_native_trace_parses_with_defaults() -> None:
    trace = parse_trace(_native(usage={"total_tokens": 5}, latency_ms=12.5, notes="n"))
    assert trace.format == "tool_calls"
    assert trace.calls[0].tool_name == "flight.get_status"
    assert not trace.calls[0].has_observed_result
    assert trace.usage is not None and trace.usage.total_tokens == 5
    assert trace.latency_ms == 12.5


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        ([], "must be a JSON object"),
        ({k: v for k, v in _native().items() if k != "schema_version"}, "schema_version"),
        (_native(schema_version="2.0"), "Unsupported trace schema_version"),
        (_native(format="langchain"), "Unsupported trace format"),
        (_native(unexpected=True), "unexpected: Extra inputs are not permitted"),
        (_native(agent={"name": ""}), "agent.name"),
        (_native(agent={"name": "a", "extra": 1}), "agent.extra"),
        (_native(scenario={}), "exactly one of 'builtin' or 'path'"),
        (
            _native(scenario={"builtin": "jfk-lhr-delay", "path": "x.json"}),
            "exactly one of 'builtin' or 'path'",
        ),
        (
            _native(scenario={"builtin": "jfk-lhr-delay", "expectation_path": "e.json"}),
            "only allowed with 'path'",
        ),
        (_native(scenario={"builtin": "../etc/passwd"}), "scenario.builtin"),
        (_native(calls=[{"tool_name": ""}]), "calls.0.tool_name"),
        (_native(calls=[{"tool_name": "a.b", "arguments": []}]), "calls.0.arguments"),
        (_native(calls=[{"tool_name": "a.b", "result": {}}]), "calls.0.result"),
        (
            _native(calls=[{"tool_name": "a.b", "observed_result": None, "observed_error": "e"}]),
            "at most one of 'observed_result' or 'observed_error'",
        ),
        (_native(latency_ms=-1), "latency_ms"),
        (_native(usage={"total_tokens": -1}), "usage.total_tokens"),
    ],
)
def test_native_trace_validation_errors(doc: Any, message: str) -> None:
    with pytest.raises(TraceFormatError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_trace(doc)


def test_observed_result_null_counts_as_present() -> None:
    trace = parse_trace(_native(calls=[{"tool_name": "a.b", "observed_result": None}]))
    assert trace.calls[0].has_observed_result
    assert trace.calls[0].observed_result is None


def test_native_tool_names_are_unsanitized() -> None:
    trace = parse_trace(_native(calls=[{"tool_name": "flight__get_status"}]))
    assert trace.calls[0].tool_name == "flight.get_status"


@pytest.mark.parametrize(
    ("provider", "internal"),
    [
        ("flight__get_status", "flight.get_status"),
        ("flight__search_flights", "flight.search_flights"),
        ("booking__confirm_rebooking", "booking.confirm_rebooking"),
        ("policy__get_rebooking_rules", "policy.get_rebooking_rules"),
        ("flight.get_status", "flight.get_status"),
    ],
)
def test_provider_tool_name_unsanitizing(provider: str, internal: str) -> None:
    assert _provider_to_internal_tool_name(provider) == internal


# ---------------------------------------------------------------------------
# OpenAI chat-completions transcripts
# ---------------------------------------------------------------------------


def test_openai_transcript_maps_calls_results_and_final_response() -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Where is AS142?"},
        {
            "role": "assistant",
            "content": None,
            "refusal": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "flight__get_status",
                        "arguments": '{"flight_id": "AS142", "operating_day": "2026-07-28"}',
                    },
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "flight__search_flights", "arguments": ""},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"status": "delayed"}'},
        {"role": "tool", "tool_call_id": "call_2", "content": "plain text, not JSON"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "AS142 "},
                {"type": "text", "text": "is delayed."},
            ],
        },
    ]
    trace = parse_trace(_chat(messages, usage={"total_tokens": 9, "model_calls": 2}, notes="n"))

    assert trace.format == "tool_calls"
    assert [c.tool_name for c in trace.calls] == ["flight.get_status", "flight.search_flights"]
    assert [c.call_id for c in trace.calls] == ["call_1", "call_2"]
    assert trace.calls[0].arguments == {"flight_id": "AS142", "operating_day": "2026-07-28"}
    assert trace.calls[1].arguments == {}
    assert trace.calls[0].observed_result == {"status": "delayed"}
    assert trace.calls[1].observed_result == "plain text, not JSON"
    assert trace.final_response == "AS142 is delayed."
    assert trace.usage is not None and trace.usage.model_calls == 2
    assert trace.notes == "n"


def test_openai_transcript_without_tool_reply_has_no_observation() -> None:
    trace = parse_trace(_chat([_assistant_call("c1", "flight__get_status", "{}")]))
    assert not trace.calls[0].has_observed_result
    assert trace.final_response is None


def test_openai_final_response_reset_by_later_tool_call() -> None:
    messages = [
        {"role": "assistant", "content": "thinking out loud"},
        _assistant_call("c1", "flight__get_status", "{}"),
        {"role": "tool", "tool_call_id": "c1", "content": None},
    ]
    trace = parse_trace(_chat(messages))
    assert trace.final_response is None
    assert trace.calls[0].has_observed_result
    assert trace.calls[0].observed_result is None


def test_openai_non_text_content_yields_no_final_text() -> None:
    messages = [{"role": "assistant", "content": [{"type": "image_url", "image_url": {}}]}]
    assert parse_trace(_chat(messages)).final_response is None


@pytest.mark.parametrize(
    ("messages", "message"),
    [
        ([_assistant_call("c1", "a__b", "{not json")], "not valid JSON"),
        ([_assistant_call("c1", "a__b", "[1, 2]")], "must be a JSON object"),
        (
            [_assistant_call("c1", "a__b", "{}"), _assistant_call("c1", "a__b", "{}")],
            "duplicate tool_call id",
        ),
        ([{"role": "tool", "tool_call_id": "missing", "content": "x"}], "unknown tool_call_id"),
        ([{"role": "tool", "content": "x"}], "unknown tool_call_id"),
        (
            [
                _assistant_call("c1", "a__b", "{}"),
                {"role": "tool", "tool_call_id": "c1", "content": "1"},
                {"role": "tool", "tool_call_id": "c1", "content": "2"},
            ],
            "duplicate tool message",
        ),
        ([{"role": "narrator", "content": "x"}], "messages.0.role"),
        ([], "messages"),
    ],
)
def test_openai_transcript_errors(messages: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(TraceFormatError, match=message):
        parse_trace(_chat(messages))


def test_openai_wrapper_forbids_extra_fields() -> None:
    with pytest.raises(TraceFormatError, match="calls"):
        parse_trace(_chat([{"role": "user", "content": "x"}], calls=[]))


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


def test_load_trace_reads_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(_native()), encoding="utf-8")
    assert load_trace(path).agent.name == "agent-x"


def test_load_trace_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TraceFormatError, match="Cannot read trace file"):
        load_trace(tmp_path / "absent.json")


def test_load_trace_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_bytes(b"\xff{")
    with pytest.raises(TraceFormatError, match="not valid UTF-8 JSON"):
        load_trace(path)


def test_load_trace_rejects_oversized_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "t.json"
    path.write_text(json.dumps(_native()), encoding="utf-8")
    monkeypatch.setattr(trace_format, "MAX_TRACE_BYTES", 10)
    with pytest.raises(TraceFormatError, match="exceeds 10 bytes"):
        load_trace(path)

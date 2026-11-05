"""Versioned import formats for externally produced agent tool-call traces.

Two input forms are accepted and both normalise to :class:`AgentTrace`:

* ``"format": "tool_calls"`` (default): the native, schema-versioned trace.
* ``"format": "openai_chat"``: an OpenAI chat-completions message transcript
  (assistant ``tool_calls`` plus ``tool`` messages) wrapped with the same
  scenario and agent metadata.

Everything an imported trace says about tool *results* is an agent claim. The
replay policy only uses it to detect divergence; it never reaches the journal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

TRACE_SCHEMA_VERSION = "1.0"
"""Current (and only) supported trace ``schema_version``."""

MAX_TRACE_BYTES = 5 * 1024 * 1024
"""Upper bound on trace file size accepted by :func:`load_trace`."""

_BUILTIN_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,127}$"


class TraceFormatError(ValueError):
    """Raised when a trace document cannot be parsed or fails validation."""


def _provider_to_internal_tool_name(name: str) -> str:
    """Map a provider-sanitized tool name back to its dotted internal name.

    Provider function names cannot contain ``.``, so the agent adapter encodes
    ``flight.get_status`` as ``flight__get_status``. Already-dotted names pass
    through unchanged. This is the single decoding point for imported traces;
    it mirrors ``flight_agent_evaluator.agent.tool_names.from_provider_tool_name``.
    """
    return name.replace("__", ".")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScenarioReference(_StrictModel):
    """Which scenario the trace was produced against.

    Exactly one of ``builtin`` (a packaged scenario id such as
    ``"jfk-lhr-delay"`` or ``"approval-denied"``) or ``path`` (a scenario JSON
    file, relative paths resolve against the trace file's directory) is set.
    ``expectation_path`` names the authored expectation for a ``path``
    scenario; built-in scenarios always use their packaged expectation.
    """

    builtin: str | None = Field(default=None, pattern=_BUILTIN_ID_PATTERN)
    path: str | None = Field(default=None, min_length=1)
    expectation_path: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_source(self) -> ScenarioReference:
        if (self.builtin is None) == (self.path is None):
            raise ValueError("scenario must set exactly one of 'builtin' or 'path'")
        if self.builtin is not None and self.expectation_path is not None:
            raise ValueError(
                "'expectation_path' is only allowed with 'path'; built-in scenarios use "
                "their packaged expectation"
            )
        return self


class AgentMetadata(_StrictModel):
    """Self-reported identity of the agent that produced the trace."""

    name: str = Field(min_length=1, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    framework: str | None = Field(default=None, max_length=128)
    version: str | None = Field(default=None, max_length=64)


class TraceUsage(_StrictModel):
    """Optional self-reported token usage for the whole run."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)


class TraceToolCall(_StrictModel):
    """One tool call the agent issued, in issue order.

    ``observed_result`` is the payload the agent says it received; set it to
    any JSON value (including ``null``) to have it checked for divergence.
    ``observed_error`` instead records that the agent saw a failure. Both are
    optional and mutually exclusive. Arguments may use ``{"$ref_step": i,
    "json_pointer": "/x"}`` or ``"$ref:i/x"`` to reference the *environment*
    result of an earlier successful call (0-based index into ``calls``).
    """

    call_id: str | None = Field(default=None, min_length=1, max_length=256)
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    observed_result: Any = None
    observed_error: str | None = Field(default=None, min_length=1)

    @field_validator("tool_name")
    @classmethod
    def _decode_tool_name(cls, value: str) -> str:
        return _provider_to_internal_tool_name(value)

    @model_validator(mode="after")
    def _single_observation(self) -> TraceToolCall:
        if "observed_result" in self.model_fields_set and self.observed_error is not None:
            raise ValueError("set at most one of 'observed_result' or 'observed_error'")
        return self

    @property
    def has_observed_result(self) -> bool:
        """Whether the trace explicitly supplied ``observed_result``."""
        return "observed_result" in self.model_fields_set


class AgentTrace(_StrictModel):
    """Native trace format (``"format": "tool_calls"``), schema version 1.0."""

    schema_version: Literal["1.0"]
    format: Literal["tool_calls"] = "tool_calls"
    scenario: ScenarioReference
    agent: AgentMetadata
    calls: list[TraceToolCall] = Field(default_factory=list, max_length=1000)
    final_response: str | None = None
    usage: TraceUsage | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=4000)
    """Free-form provenance note (e.g. how the trace was produced)."""


# ---------------------------------------------------------------------------
# OpenAI chat-completions transcript form
# ---------------------------------------------------------------------------


class _OpenAIFunction(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    name: str = Field(min_length=1)
    arguments: str = "{}"


class _OpenAIToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1)
    type: Literal["function"] = "function"
    function: _OpenAIFunction


class OpenAIChatMessage(BaseModel):
    """Subset of a chat-completions message used for trace import.

    Unknown provider fields (``refusal``, ``annotations``, ...) are ignored so
    SDK ``model_dump()`` output can be imported as-is.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[_OpenAIToolCall] | None = None
    tool_call_id: str | None = None


class OpenAIChatTrace(_StrictModel):
    """OpenAI transcript form (``"format": "openai_chat"``), schema version 1.0."""

    schema_version: Literal["1.0"]
    format: Literal["openai_chat"]
    scenario: ScenarioReference
    agent: AgentMetadata
    messages: list[OpenAIChatMessage] = Field(min_length=1, max_length=5000)
    usage: TraceUsage | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=4000)

    def to_agent_trace(self) -> AgentTrace:
        """Normalise the transcript into the native :class:`AgentTrace`."""
        calls: list[dict[str, Any]] = []
        index_by_id: dict[str, int] = {}
        final_response: str | None = None

        for position, message in enumerate(self.messages):
            if message.role == "assistant":
                if message.tool_calls:
                    for tc in message.tool_calls:
                        if tc.id in index_by_id:
                            raise TraceFormatError(
                                f"messages[{position}]: duplicate tool_call id {tc.id!r}"
                            )
                        index_by_id[tc.id] = len(calls)
                        calls.append(
                            {
                                "call_id": tc.id,
                                "tool_name": tc.function.name,
                                "arguments": _parse_arguments(tc.function.arguments, position),
                            }
                        )
                    final_response = None
                else:
                    final_response = _message_text(message.content)
            elif message.role == "tool":
                if message.tool_call_id is None or message.tool_call_id not in index_by_id:
                    raise TraceFormatError(
                        f"messages[{position}]: tool message references unknown "
                        f"tool_call_id {message.tool_call_id!r}"
                    )
                call = calls[index_by_id[message.tool_call_id]]
                if "observed_result" in call:
                    raise TraceFormatError(
                        f"messages[{position}]: duplicate tool message for "
                        f"tool_call_id {message.tool_call_id!r}"
                    )
                call["observed_result"] = _parse_tool_content(message.content)

        return _validate(
            AgentTrace,
            {
                "schema_version": self.schema_version,
                "scenario": self.scenario.model_dump(exclude_none=True),
                "agent": self.agent.model_dump(exclude_none=True),
                "calls": calls,
                "final_response": final_response,
                "usage": self.usage.model_dump() if self.usage else None,
                "latency_ms": self.latency_ms,
                "notes": self.notes,
            },
        )


def _parse_arguments(raw: str, position: int) -> dict[str, Any]:
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise TraceFormatError(
            f"messages[{position}]: tool_call arguments are not valid JSON: {exc.msg}"
        ) from exc
    if not isinstance(parsed, dict):
        raise TraceFormatError(f"messages[{position}]: tool_call arguments must be a JSON object")
    return parsed


def _message_text(content: str | list[dict[str, Any]] | None) -> str | None:
    if content is None or isinstance(content, str):
        return content
    parts = [str(p.get("text", "")) for p in content if p.get("type") == "text"]
    return "".join(parts) if parts else None


def _parse_tool_content(content: str | list[dict[str, Any]] | None) -> Any:
    text = _message_text(content)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ---------------------------------------------------------------------------
# Parsing entry points
# ---------------------------------------------------------------------------


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _validate(model: type[_ModelT], data: Any) -> _ModelT:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        raise TraceFormatError(f"Invalid {model.__name__}: {details}") from exc


def parse_trace(data: Any) -> AgentTrace:
    """Validate a decoded JSON document in either supported form."""
    if not isinstance(data, dict):
        raise TraceFormatError("Trace document must be a JSON object")
    version = data.get("schema_version")
    if version != TRACE_SCHEMA_VERSION:
        raise TraceFormatError(
            f"Unsupported trace schema_version {version!r}; expected {TRACE_SCHEMA_VERSION!r}"
        )
    form = data.get("format", "tool_calls")
    if form == "tool_calls":
        return _validate(AgentTrace, data)
    if form == "openai_chat":
        return _validate(OpenAIChatTrace, data).to_agent_trace()
    raise TraceFormatError(
        f"Unsupported trace format {form!r}; expected 'tool_calls' or 'openai_chat'"
    )


def load_trace(path: Path) -> AgentTrace:
    """Read, decode and validate a trace file."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise TraceFormatError(f"Cannot read trace file {path}: {exc}") from exc
    if size > MAX_TRACE_BYTES:
        raise TraceFormatError(f"Trace file {path} exceeds {MAX_TRACE_BYTES} bytes")
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TraceFormatError(f"Trace file {path} is not valid UTF-8 JSON: {exc}") from exc
    return parse_trace(data)


__all__ = [
    "MAX_TRACE_BYTES",
    "TRACE_SCHEMA_VERSION",
    "AgentMetadata",
    "AgentTrace",
    "OpenAIChatMessage",
    "OpenAIChatTrace",
    "ScenarioReference",
    "TraceFormatError",
    "TraceToolCall",
    "TraceUsage",
    "load_trace",
    "parse_trace",
]

"""Unit tests for model clients, provider tool-name mapping, and live-model guardrails."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from flight_agent_evaluator.agent.errors import (
    ModelClientConfigurationError,
    ModelProviderError,
    ModelReplayFingerprintMismatchError,
    ModelReplayManifestInvalidError,
    ModelReplayMissingExchangeError,
)
from flight_agent_evaluator.agent.model_client import (
    ModelAgentSettings,
    OpenAIChatCompletionsClient,
    ReplayModelClient,
    build_model_client,
    model_exchange_manifest_path,
    write_model_exchange_manifest,
)
from flight_agent_evaluator.agent.tool_names import (
    PROVIDER_TOOL_NAME_PATTERN,
    ToolNameEncodingError,
    from_provider_tool_name,
    to_provider_tool_name,
)
from flight_agent_evaluator.contracts.model import (
    ModelConfiguration,
    ModelErrorType,
    ModelExchange,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
)
from flight_agent_evaluator.tools.base import build_transactional_registry

SECRET_KEY = "sk-test-SECRET-never-logged"


def _request(turn: int = 0, tools: list[dict[str, Any]] | None = None) -> ModelRequest:
    return ModelRequest(
        model_id="gpt-4o-mini",
        prompt_policy_id="p1",
        prompt_policy_version="1.0",
        prompt_digest="abc",
        turn_index=turn,
        messages=[{"role": "user", "content": "hello"}],
        tools=tools or [],
        model_configuration=ModelConfiguration(),
    )


def _exchange(req: ModelRequest, content: str = "world") -> ModelExchange:
    resp = ModelResponse(role="assistant", content=content)
    return ModelExchange(
        turn_index=req.turn_index,
        request=req,
        response=resp,
        request_fingerprint=req.canonical_fingerprint(),
        response_digest=resp.canonical_digest(),
    )


def _completion(message: dict[str, Any], finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


# ---------------------------------------------------------------------------
# Provider tool-name mapping
# ---------------------------------------------------------------------------


def test_every_registered_tool_name_maps_reversibly_to_provider_pattern() -> None:
    names = build_transactional_registry().tool_names()
    assert any("." in name for name in names)
    for name in names:
        encoded = to_provider_tool_name(name)
        assert PROVIDER_TOOL_NAME_PATTERN.fullmatch(encoded), encoded
        assert from_provider_tool_name(encoded) == name


@pytest.mark.parametrize("bad_name", ["a__b", "a_.b", "tool with space", "x" * 65])
def test_ambiguous_or_invalid_tool_names_are_rejected(bad_name: str) -> None:
    with pytest.raises(ToolNameEncodingError):
        to_provider_tool_name(bad_name)


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def test_request_contract_has_no_transport_label() -> None:
    with pytest.raises(ValidationError):
        ModelRequest(
            provider="openai",  # type: ignore[call-arg]
            prompt_policy_id="p1",
            prompt_policy_version="1.0",
            prompt_digest="abc",
            turn_index=0,
            messages=[],
        )


def test_fingerprint_covers_model_behaviour_inputs() -> None:
    base = _request()
    assert (
        base.canonical_fingerprint()
        != base.model_copy(update={"model_id": "other"}).canonical_fingerprint()
    )
    assert (
        base.canonical_fingerprint()
        != base.model_copy(update={"prompt_digest": "def"}).canonical_fingerprint()
    )
    assert (
        base.canonical_fingerprint()
        != base.model_copy(
            update={"model_configuration": ModelConfiguration(temperature=0.5)}
        ).canonical_fingerprint()
    )


# ---------------------------------------------------------------------------
# Replay client
# ---------------------------------------------------------------------------


def test_replay_model_client_basic_execution() -> None:
    req = _request()
    client = ReplayModelClient([_exchange(req)])
    assert client.provider == "replay"
    client.begin_run(scenario_id="s", run_id="r", configuration=ModelConfiguration())
    res = asyncio.run(client.create_completion(req))
    assert res.content == "world"
    manifest = asyncio.run(client.end_run())
    assert manifest.manifest_id == "s__r"
    assert [e.request_fingerprint for e in manifest.exchanges] == [req.canonical_fingerprint()]


def test_replay_mismatch_and_missing_exchange_fail_closed() -> None:
    req = _request()
    client = ReplayModelClient([_exchange(req)])
    client.begin_run(scenario_id="s", run_id="r", configuration=ModelConfiguration())
    with pytest.raises(ModelReplayFingerprintMismatchError):
        asyncio.run(client.create_completion(req.model_copy(update={"prompt_digest": "x"})))
    with pytest.raises(ModelReplayMissingExchangeError):
        asyncio.run(client.create_completion(_request(turn=5)))


def test_replay_rejects_duplicate_fingerprints() -> None:
    req = _request()
    with pytest.raises(ModelReplayManifestInvalidError):
        ReplayModelClient([_exchange(req), _exchange(req)])


def test_replay_directory_loads_manifest_per_run(tmp_path: Path) -> None:
    req = _request()
    manifest = ModelExchangeManifest(
        manifest_id="scn__run-1",
        model_configuration=ModelConfiguration(),
        exchanges=[_exchange(req)],
    )
    write_model_exchange_manifest(
        model_exchange_manifest_path(tmp_path, "scn", "run-1", "0" * 64), manifest
    )
    client = ReplayModelClient.from_directory(tmp_path)

    with pytest.raises(ModelReplayMissingExchangeError, match="not found"):
        client.begin_run(scenario_id="scn", run_id="run-2", configuration=ModelConfiguration())
    with pytest.raises(ModelReplayFingerprintMismatchError, match="configuration mismatch"):
        client.begin_run(
            scenario_id="scn",
            run_id="run-1",
            configuration=ModelConfiguration(model_id="other-model"),
        )

    client.begin_run(scenario_id="scn", run_id="run-1", configuration=ModelConfiguration())
    assert asyncio.run(client.create_completion(req)).content == "world"
    assert asyncio.run(client.end_run()).semantic_digest() == manifest.semantic_digest()


def test_replay_directory_rejects_manifest_bound_to_another_run(tmp_path: Path) -> None:
    manifest = ModelExchangeManifest(
        manifest_id="other__run", model_configuration=ModelConfiguration()
    )
    write_model_exchange_manifest(
        model_exchange_manifest_path(tmp_path, "scn", "r", "0" * 64), manifest
    )
    client = ReplayModelClient.from_directory(tmp_path)
    with pytest.raises(ModelReplayManifestInvalidError):
        client.begin_run(scenario_id="scn", run_id="r", configuration=ModelConfiguration())


def test_manifest_file_uses_lf_line_endings(tmp_path: Path) -> None:
    # Committed live manifests must be byte-identical whether recorded on Windows or Linux.
    path = tmp_path / "m.json"
    write_model_exchange_manifest(
        path,
        ModelExchangeManifest(manifest_id="scn__run", model_configuration=ModelConfiguration()),
    )
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")


def test_malformed_manifest_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelReplayManifestInvalidError):
        build_model_client(ModelAgentSettings(replay_manifest=path))


# ---------------------------------------------------------------------------
# Live-model guardrails
# ---------------------------------------------------------------------------


def test_replay_is_default_and_requires_a_recorded_source() -> None:
    with pytest.raises(ModelClientConfigurationError, match="--model-replay-manifest PATH"):
        build_model_client(ModelAgentSettings())


def test_replay_directory_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ModelClientConfigurationError, match="directory not found"):
        build_model_client(ModelAgentSettings(replay_dir=tmp_path / "missing"))


@pytest.mark.parametrize("mode", ["live", "record"])
def test_network_modes_require_allow_live_model(mode: str, tmp_path: Path) -> None:
    settings = ModelAgentSettings(mode=mode, record_dir=tmp_path)  # type: ignore[arg-type]
    with pytest.raises(ModelClientConfigurationError, match="--allow-live-model"):
        build_model_client(settings, environ={"OPENAI_API_KEY": SECRET_KEY})


def test_network_modes_require_named_api_key_env(tmp_path: Path) -> None:
    settings = ModelAgentSettings(
        mode="record", record_dir=tmp_path, allow_live_model=True, api_key_env="MY_GATEWAY_KEY"
    )
    with pytest.raises(ModelClientConfigurationError, match="MY_GATEWAY_KEY"):
        build_model_client(settings, environ={"OPENAI_API_KEY": SECRET_KEY})
    client = build_model_client(settings, environ={"MY_GATEWAY_KEY": SECRET_KEY})
    assert isinstance(client, OpenAIChatCompletionsClient)
    assert SECRET_KEY not in repr(client)


def test_record_mode_requires_output_directory() -> None:
    settings = ModelAgentSettings(mode="record", allow_live_model=True)
    with pytest.raises(ModelClientConfigurationError, match="output directory"):
        build_model_client(settings, environ={"OPENAI_API_KEY": SECRET_KEY})
    with pytest.raises(ModelClientConfigurationError):
        OpenAIChatCompletionsClient(api_key=SECRET_KEY, mode="record")


# ---------------------------------------------------------------------------
# Chat Completions wire format (in-process fake server, no network)
# ---------------------------------------------------------------------------


def test_chat_completions_client_maps_tool_names_at_the_wire(tmp_path: Path) -> None:
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        assert request.headers["authorization"] == f"Bearer {SECRET_KEY}"
        return httpx.Response(
            200,
            json=_completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "flight__get_status",
                                "arguments": '{"flight_id": "AS142"}',
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
            ),
        )

    tools = [
        {
            "type": "function",
            "function": {"name": "flight.get_status", "description": "d", "parameters": {}},
        }
    ]
    req = _request(tools=tools).model_copy(
        update={
            "messages": [
                {"role": "user", "content": "hi"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_0",
                            "type": "function",
                            "function": {"name": "flight.search_flights", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_0", "content": "{}"},
            ]
        }
    )

    async def scenario() -> tuple[ModelResponse, ModelExchangeManifest]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OpenAIChatCompletionsClient(
                api_key=SECRET_KEY,
                mode="record",
                record_dir=tmp_path,
                base_url="http://fake-openai.local/v1",
                http_client=http_client,
            )
            client.begin_run(scenario_id="scn", run_id="run", configuration=ModelConfiguration())
            response = await client.create_completion(req)
            return response, await client.end_run()

    response, manifest = asyncio.run(scenario())

    wire = captured[0]
    assert [t["function"]["name"] for t in wire["tools"]] == ["flight__get_status"]
    assert wire["messages"][1]["tool_calls"][0]["function"]["name"] == "flight__search_flights"
    assert response.tool_calls[0].tool_name == "flight.get_status"
    assert response.tool_calls[0].arguments == {"flight_id": "AS142"}
    # Internal names are preserved in the recorded exchange.
    assert manifest.exchanges[0].request.tools[0]["function"]["name"] == "flight.get_status"
    assert manifest.configuration_digest is not None
    written = model_exchange_manifest_path(tmp_path, "scn", "run", manifest.configuration_digest)
    assert ModelExchangeManifest.model_validate_json(written.read_text("utf-8")) == manifest


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, ModelErrorType.AUTHENTICATION),
        (400, ModelErrorType.PROVIDER_UNAVAILABLE),
    ],
)
def test_chat_completions_provider_errors_are_typed_and_secret_free(
    status: int, error_type: ModelErrorType
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(status, json={"error": {"message": f"bad key {SECRET_KEY}"}})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OpenAIChatCompletionsClient(
                api_key=SECRET_KEY,
                mode="live",
                base_url="http://fake-openai.local/v1",
                http_client=http_client,
            )
            client.begin_run(scenario_id="s", run_id="r", configuration=ModelConfiguration())
            try:
                await client.create_completion(_request())
            finally:
                await client.end_run()

    with pytest.raises(ModelProviderError) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.error.error_type == error_type
    assert SECRET_KEY not in str(excinfo.value)


def test_malformed_tool_arguments_are_typed_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(
            200,
            json=_completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "flight__get_status", "arguments": "[1"},
                        }
                    ],
                },
                finish_reason="tool_calls",
            ),
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OpenAIChatCompletionsClient(
                api_key=SECRET_KEY,
                mode="live",
                base_url="http://fake-openai.local/v1",
                http_client=http_client,
            )
            client.begin_run(scenario_id="s", run_id="r", configuration=ModelConfiguration())
            response = await client.create_completion(_request())
            assert response.tool_calls[0].arguments_error is not None
            assert response.tool_calls[0].raw_arguments == "[1"
            manifest = await client.end_run()
            assert manifest.exchanges[0].response == response

    asyncio.run(scenario())


def test_record_manifest_never_contains_planted_api_keys(tmp_path: Path) -> None:
    """Secret-bearing exchanges cannot be persisted or silently rewritten."""
    gateway_key = "gw-live-0123456789abcdef"  # custom format: only caught as the real key value
    project_key = "sk-proj-AbCdEf_0123456789-ghijklmnop"

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(
            200,
            json=_completion(
                {
                    "role": "assistant",
                    "content": f"Your keys are {gateway_key} and {project_key}.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "flight__get_status",
                                "arguments": json.dumps({"flight_id": gateway_key}),
                            },
                        }
                    ],
                },
                finish_reason="tool_calls",
            ),
        )

    req = _request().model_copy(
        update={"messages": [{"role": "user", "content": f"use {project_key} / {gateway_key}"}]}
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OpenAIChatCompletionsClient(
                api_key=gateway_key,
                mode="record",
                record_dir=tmp_path,
                base_url="http://fake-openai.local/v1",
                http_client=http_client,
            )
            client.begin_run(scenario_id="scn", run_id="run", configuration=ModelConfiguration())
            await client.create_completion(req)
            await client.end_run()

    with pytest.raises(ModelProviderError, match="secret") as excinfo:
        asyncio.run(scenario())
    assert gateway_key not in str(excinfo.value)
    assert project_key not in str(excinfo.value)
    assert not list(tmp_path.glob("*.model-exchanges.json"))

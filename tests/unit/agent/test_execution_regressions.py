"""Regression coverage for model identity, invalid calls and execution budgets."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from tests.unit.agent.test_agent_loop import (
    ScriptedClient,
    _executor,
    _make_context,
    _wire_completion,
)

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    ModelAgentSettings,
    OpenAIChatCompletionsClient,
    ReplayModelClient,
    model_agent_configuration_digest,
)
from flight_agent_evaluator.contracts.model import (
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelErrorType,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.state import StateSnapshot


def test_configuration_identity_distinguishes_models_and_prompts() -> None:
    first = ModelToolCallingAgent(ScriptedClient([ModelResponse(content="ok")]))
    other = ModelToolCallingAgent(
        ScriptedClient([ModelResponse(content="ok")]),
        model_configuration=ModelConfiguration(model_id="other"),
    )
    assert first.configuration_digest != other.configuration_digest
    changed = ModelToolCallingAgent(
        ScriptedClient([]),
        prompt_policy=first.prompt_policy.model_copy(update={"content": "different"}),
    )
    assert first.configuration_digest != changed.configuration_digest


@pytest.mark.parametrize(
    "arguments",
    ["{bad", "[]", '{"flight_id":"a","flight_id":"b"}', '{"x":NaN}', '{"x":1e999}'],
)
def test_malformed_call_record_replay_is_exact(tmp_path: Path, arguments: str) -> None:
    calls = 0
    sent_tools_digest: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls, sent_tools_digest
        calls += 1
        if calls == 1:
            sent_tools_digest = hashlib.sha256(
                json.dumps(
                    json.loads(request.content)["tools"], sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "bad",
                        "type": "function",
                        "function": {"name": "flight__get_status", "arguments": arguments},
                    }
                ],
            }
            return httpx.Response(200, json=_wire_completion(message, "tool_calls"))
        body = json.loads(request.content)
        assert "input schema" in body["messages"][-1]["content"]
        return httpx.Response(
            200, json=_wire_completion({"role": "assistant", "content": "recovered"}, "stop")
        )

    task = AgentTask(
        task_id="t",
        scenario_id="test",
        public_request="status",
        allowed_tools=["flight.get_status"],
    )
    recorded_journal = HashChainJournal()

    async def record() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            client = OpenAIChatCompletionsClient(
                api_key="mock-key", record_dir=tmp_path, http_client=transport
            )
            result = await ModelToolCallingAgent(client).execute(
                task, _executor(recorded_journal), StateSnapshot(), _make_context()
            )
            assert result.stop_reason == AgentStopReason.COMPLETED
            assert result.invalid_tool_call_count == 1
            assert result.model_provenance is not None
            assert result.model_provenance.tool_schema_digest == sent_tools_digest
            assert result.model_latency_ms is not None

    asyncio.run(record())
    replay_journal = HashChainJournal()
    result = asyncio.run(
        ModelToolCallingAgent(ReplayModelClient.from_directory(tmp_path)).execute(
            task, _executor(replay_journal), StateSnapshot(), _make_context()
        )
    )
    assert result.final_response == "recovered"
    assert recorded_journal.final_digest() == replay_journal.final_digest()
    assert calls == 2


def test_over_budget_calls_are_all_journaled() -> None:
    journal = HashChainJournal()
    client = ScriptedClient(
        [
            ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        call_id=str(i),
                        tool_name="flight.get_status",
                        arguments={"flight_id": "AS142", "operating_day": "2026-07-28"},
                    )
                    for i in range(3)
                ]
            )
        ]
    )
    result = asyncio.run(
        ModelToolCallingAgent(client).execute(
            AgentTask(
                task_id="t",
                scenario_id="test",
                public_request="status",
                allowed_tools=["flight.get_status"],
                tool_call_limit=1,
            ),
            _executor(journal),
            StateSnapshot(),
            _make_context(),
        )
    )
    assert result.stop_reason == AgentStopReason.TOOL_LIMIT_EXCEEDED
    assert result.tool_call_count == 3
    results = [entry.payload for entry in journal.entries if entry.type == "tool_result"]
    assert len(results) == 3
    assert [item["error"]["error_type"] for item in results[1:]] == ["tool_call_limit_exceeded"] * 2


def test_model_call_timeout_returns_typed_warning() -> None:
    class SlowClient(ScriptedClient):
        async def create_completion(self, request: ModelRequest) -> ModelResponse:
            await asyncio.sleep(10)
            return ModelResponse(content="late")

    agent = ModelToolCallingAgent(
        SlowClient([]), model_configuration=ModelConfiguration(request_timeout_seconds=0.001)
    )
    result = asyncio.run(
        agent.execute(
            AgentTask(task_id="t", scenario_id="test", public_request="status"),
            _executor(HashChainJournal()),
            StateSnapshot(),
            _make_context(),
        )
    )
    assert result.stop_reason == AgentStopReason.ERROR
    assert any("timeout" in warning for warning in result.warnings)
    assert result.model_latency_ms is not None and result.model_latency_ms > 0


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (500, ModelErrorType.PROVIDER_UNAVAILABLE),
        (200, ModelErrorType.INVALID_RESPONSE),
    ],
    ids=["http-500", "invalid-json"],
)
def test_provider_failure_returns_typed_warning_and_persists_manifest(
    tmp_path: Path, status_code: int, expected_error: ModelErrorType
) -> None:
    secret = "sk-planted-provider-response-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=f"invalid JSON provider payload {secret}",
            headers={"Content-Type": "application/json"},
        )

    async def record() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            client = OpenAIChatCompletionsClient(
                api_key="mock-key", record_dir=tmp_path, http_client=transport
            )
            result = await ModelToolCallingAgent(client).execute(
                AgentTask(task_id="t", scenario_id="test", public_request="status"),
                _executor(HashChainJournal()),
                StateSnapshot(),
                _make_context(),
            )
            assert result.stop_reason == AgentStopReason.ERROR
            assert result.final_response is None
            assert any(
                warning.startswith(f"{expected_error.value}:") for warning in result.warnings
            )
            assert secret not in result.model_dump_json()
            manifests = list(tmp_path.glob("*.model-exchanges.json"))
            assert len(manifests) == 1
            manifest = ModelExchangeManifest.model_validate_json(
                manifests[0].read_text(encoding="utf-8")
            )
            assert manifest.exchanges == []
            assert result.model_exchange_digest == manifest.semantic_digest()
            assert result.model_provenance is not None
            assert (
                result.model_provenance.model_exchange_manifest_digest == manifest.semantic_digest()
            )
            assert secret not in manifests[0].read_text(encoding="utf-8")

    asyncio.run(record())


def test_manifest_names_and_provenance_bind_model_configuration(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_wire_completion({"role": "assistant", "content": "done"}, "stop"),
        )

    async def record() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            identities: list[str] = []
            for model in ("first", "second"):
                config = ModelConfiguration(model_id=model)
                client = OpenAIChatCompletionsClient(
                    api_key="mock-key",
                    record_dir=tmp_path,
                    base_url="https://user:pass@example.test:1234/v1?key=private",
                    http_client=transport,
                )
                agent = ModelToolCallingAgent(client, model_configuration=config)
                assert agent.configuration_digest == model_agent_configuration_digest(
                    ModelAgentSettings(
                        mode="record",
                        model_configuration=config,
                        base_url="https://user:pass@example.test:1234/v1?key=private",
                    )
                )
                identities.append(agent.configuration_digest)
                result = await agent.execute(
                    AgentTask(task_id="t", scenario_id="test", public_request="status"),
                    _executor(HashChainJournal()),
                    StateSnapshot(),
                    _make_context(),
                )
                assert result.model_provenance is not None
                assert result.model_provenance.endpoint_host == "example.test"
                assert result.model_provenance.model_id == model
                assert (
                    result.model_provenance.model_exchange_manifest_digest
                    == result.model_exchange_digest
                )
            assert identities[0] != identities[1]
            names = [path.name for path in tmp_path.glob("*.model-exchanges.json")]
            assert len(names) == 2
            assert all(any(digest[:12] in name for name in names) for digest in identities)

    asyncio.run(record())


@pytest.mark.parametrize("secret_in", ["request", "response"])
def test_secret_bearing_record_run_fails_without_manifest(tmp_path: Path, secret_in: str) -> None:
    secret = "sk-proj-AbCdEf_0123456789-ghijklmnop"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_wire_completion(
                {"role": "assistant", "content": secret if secret_in == "response" else "done"},
                "stop",
            ),
        )

    async def record() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            client = OpenAIChatCompletionsClient(
                api_key="mock-key",
                record_dir=tmp_path,
                http_client=transport,
            )
            result = await ModelToolCallingAgent(client).execute(
                AgentTask(
                    task_id="t",
                    scenario_id="test",
                    public_request=secret if secret_in == "request" else "status",
                ),
                _executor(HashChainJournal()),
                StateSnapshot(),
                _make_context(),
            )
            assert result.stop_reason == AgentStopReason.ERROR
            assert any("secret" in warning for warning in result.warnings)
            assert secret not in " ".join(result.warnings)

    asyncio.run(record())
    assert not list(tmp_path.glob("*.model-exchanges.json"))

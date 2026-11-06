"""End-to-end record -> replay of the model agent through the real Chat Completions wire format.

An in-process fake OpenAI-compatible server (``httpx.MockTransport``) scripts the
model's tool calls using provider-sanitized function names.  This proves the wire
format and the offline replay contract end to end; it is not a model benchmark.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from flight_agent_evaluator.agent.errors import ModelReplayMissingExchangeError
from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    MODEL_EXCHANGE_MANIFEST_SUFFIX,
    ModelAgentSettings,
    OpenAIChatCompletionsClient,
    ReplayModelClient,
)
from flight_agent_evaluator.agent.protocol import ModelClient
from flight_agent_evaluator.agent.tool_names import PROVIDER_TOOL_NAME_PATTERN
from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
from flight_agent_evaluator.benchmarks.registry import BenchmarkAgentRegistry
from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    AgentTask,
    ModelExchangeManifest,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkMetricVector, BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot

SCENARIO_PATH = Path("resources/scenarios/jfk-lhr-delay.json")
FINAL_ANSWER = (
    "AS142 is delayed by 180 minutes due to weather. Alternative flight AS144 is available."
)


class FakeChatCompletionsServer:
    """Scripted OpenAI-compatible endpoint: status lookup, alternative search, answer."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        for tool in body.get("tools", []):
            name = tool["function"]["name"]
            assert PROVIDER_TOOL_NAME_PATTERN.fullmatch(name), name
            assert "." not in name
        # Script by conversation progress so repeated runs get identical answers.
        turn = 1 + sum(1 for message in body["messages"] if message["role"] == "tool")
        if turn == 1:
            return self._tool_call(
                "call_status",
                "flight__get_status",
                {"flight_id": "AS142", "operating_day": "2026-07-28"},
            )
        if turn == 2:
            return self._tool_call(
                "call_search",
                "flight__search_flights",
                {"origin": "JFK", "destination": "LHR", "departure_date": "2026-07-28"},
            )
        return self._completion({"role": "assistant", "content": FINAL_ANSWER}, "stop")

    def _tool_call(self, call_id: str, name: str, arguments: dict[str, Any]) -> httpx.Response:
        return self._completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            },
            "tool_calls",
        )

    @staticmethod
    def _completion(message: dict[str, Any], finish_reason: str) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-e2e",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4o-mini",
                "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
            },
        )


class JournalCapturingAgent:
    """Delegates to the model agent and keeps the executor's journal for inspection."""

    def __init__(self, inner: ModelToolCallingAgent) -> None:
        self._inner = inner
        self.journal: HashChainJournal | None = None
        self.result: AgentRunResult | None = None

    @property
    def agent_id(self) -> str:
        return self._inner.agent_id

    @property
    def agent_version(self) -> str:
        return self._inner.agent_version

    @property
    def configuration_digest(self) -> str:
        return self._inner.configuration_digest

    async def execute(
        self,
        task: AgentTask,
        executor: ToolExecutor,
        state: StateSnapshot,
        context: RunContext,
    ) -> AgentRunResult:
        self.journal = executor._journal  # trusted evidence written by the executor
        self.result = await self._inner.execute(task, executor, state, context)
        return self.result


def _run(client: ModelClient) -> tuple[BenchmarkMetricVector, JournalCapturingAgent]:
    scenario = ScenarioLoader().load_from_path(SCENARIO_PATH).scenario
    agent = JournalCapturingAgent(ModelToolCallingAgent(model_client=client))
    metrics = asyncio.run(BenchmarkRunner().run_scenario(scenario, agent))
    return metrics, agent


def _tool_trajectory(journal: HashChainJournal | None) -> list[tuple[str, str]]:
    assert journal is not None
    return [
        (str(e.payload["tool_name"]), json.dumps(e.payload["arguments"], sort_keys=True))
        for e in journal.entries
        if e.type == "tool_call"
    ]


def test_model_agent_record_then_offline_replay_round_trip(tmp_path: Path) -> None:
    server = FakeChatCompletionsServer()

    async def make_record_client() -> tuple[httpx.AsyncClient, OpenAIChatCompletionsClient]:
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(server))
        return http_client, OpenAIChatCompletionsClient(
            api_key="sk-test-e2e",
            mode="record",
            record_dir=tmp_path,
            base_url="http://fake-openai.local/v1",
            http_client=http_client,
        )

    http_client, record_client = asyncio.run(make_record_client())
    recorded, record_agent = _run(record_client)
    asyncio.run(http_client.aclose())

    # Wire format: three model turns, sanitized names on the wire.
    assert len(server.requests) == 3
    assert record_agent.result is not None
    assert record_agent.result.stop_reason == AgentStopReason.COMPLETED, (
        record_agent.result.warnings
    )
    assert record_agent.result.final_response == FINAL_ANSWER
    assert recorded.task_success, recorded.failure_codes
    assert recorded.safety_pass

    # Journal carries internal dotted names.
    record_trajectory = _tool_trajectory(record_agent.journal)
    assert [name for name, _ in record_trajectory] == [
        "flight.get_status",
        "flight.search_flights",
    ]

    # One manifest per scenario run, holding internal names.
    manifests = list(tmp_path.glob(f"*{MODEL_EXCHANGE_MANIFEST_SUFFIX}"))
    assert len(manifests) == 1
    assert manifests[0].name.startswith(f"jfk-lhr-delay__{recorded.run_id}")
    manifest = ModelExchangeManifest.model_validate_json(manifests[0].read_text("utf-8"))
    assert len(manifest.exchanges) == 3
    assert manifest.exchanges[1].request.tools[0]["function"]["name"].count(".") == 1

    # Offline replay from the directory reproduces the run exactly, with zero network calls.
    replayed, replay_agent = _run(ReplayModelClient.from_directory(tmp_path))
    assert len(server.requests) == 3
    assert replay_agent.result is not None
    assert replay_agent.result.stop_reason == AgentStopReason.COMPLETED
    assert replay_agent.result.final_response == FINAL_ANSWER
    assert replayed.task_success
    assert _tool_trajectory(replay_agent.journal) == record_trajectory
    assert replayed.journal_digest == recorded.journal_digest
    assert replay_agent.result.model_exchange_digest == record_agent.result.model_exchange_digest


def test_benchmark_engine_records_and_replays_model_agent_per_scenario_rep(tmp_path: Path) -> None:
    """`benchmark run --agents model`: one manifest per scenario/rep, offline replay by default."""
    server = FakeChatCompletionsServer()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(server))
    record_dir = tmp_path / "model-exchanges"

    record_registry = BenchmarkAgentRegistry(
        model_settings=ModelAgentSettings(
            mode="record",
            record_dir=record_dir,
            base_url="http://fake-openai.local/v1",
            allow_live_model=True,
        )
    )
    meta = record_registry.get_metadata("model")
    record_registry.register(
        agent_id="model",
        factory=lambda: ModelToolCallingAgent(
            model_client=OpenAIChatCompletionsClient(
                api_key="sk-test-e2e",
                mode="record",
                record_dir=record_dir,
                base_url="http://fake-openai.local/v1",
                http_client=http_client,
            )
        ),
        agent_version=meta["agent_version"],
        implementation=meta["implementation"],
    )
    recorded = CanonicalBenchmarkEngine(registry=record_registry).run_benchmark(
        agent_ids=["model"], scenario_filter=["jfk-lhr-delay"], repetitions=2
    )
    asyncio.run(http_client.aclose())
    requests_after_record = len(server.requests)

    manifests = sorted(record_dir.glob(f"*{MODEL_EXCHANGE_MANIFEST_SUFFIX}"))
    assert len(manifests) == 2
    assert {case.run_id for case in recorded.case_results} == {
        ModelExchangeManifest.model_validate_json(m.read_bytes()).manifest_id.removeprefix(
            "jfk-lhr-delay__"
        )
        for m in manifests
    }
    assert all(case.task_success for case in recorded.case_results)

    replay_registry = BenchmarkAgentRegistry(
        model_settings=ModelAgentSettings(mode="replay", replay_dir=record_dir)
    )
    replayed = CanonicalBenchmarkEngine(registry=replay_registry).run_benchmark(
        agent_ids=["model"], scenario_filter=["jfk-lhr-delay"], repetitions=2
    )
    assert len(server.requests) == requests_after_record
    assert [c.journal_digest for c in replayed.case_results] == [
        c.journal_digest for c in recorded.case_results
    ]
    assert [c.semantic_result_digest for c in replayed.case_results] == [
        c.semantic_result_digest for c in recorded.case_results
    ]


def test_benchmark_model_replay_fails_clearly_when_manifest_missing(tmp_path: Path) -> None:
    registry = BenchmarkAgentRegistry(
        model_settings=ModelAgentSettings(mode="replay", replay_dir=tmp_path)
    )
    with pytest.raises(ModelReplayMissingExchangeError, match="not found"):
        CanonicalBenchmarkEngine(registry=registry).run_benchmark(
            agent_ids=["model"], scenario_filter=["jfk-lhr-delay"]
        )

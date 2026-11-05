"""Unit tests for ModelToolCallingAgent loop."""

from __future__ import annotations

import asyncio
import datetime
import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    OpenAIChatCompletionsClient,
    ReplayModelClient,
    model_exchange_manifest_path,
)
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.agent.protocol import ModelClient
from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_default_registry, build_transactional_registry

RUN_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def _make_context() -> RunContext:
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    id_factory = DeterministicIdFactory(scenario_id="test", scenario_version=1, seed=42)
    return RunContext(
        run_id=RUN_ID,
        scenario_id="test",
        scenario_version=1,
        seed=42,
        clock=clock,
        id_factory=id_factory,
        tool_call_limit=5,
        time_limit_seconds=60,
        correlation_id="c1",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


class ScriptedClient:
    """Test double answering each turn with a scripted response."""

    provider = "scripted"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses

    def begin_run(
        self, *, scenario_id: str, run_id: str, configuration: ModelConfiguration
    ) -> None:
        self._manifest = ModelExchangeManifest(
            manifest_id=f"{scenario_id}__{run_id}", model_configuration=configuration
        )

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        return self._responses[min(request.turn_index, len(self._responses) - 1)]

    async def end_run(self) -> ModelExchangeManifest:
        return self._manifest


def _execute(client: ModelClient, task: AgentTask, executor: ToolExecutor) -> AgentRunResult:
    agent = ModelToolCallingAgent(model_client=client, prompt_policy=get_default_prompt_policy())
    return asyncio.run(
        agent.execute(task=task, executor=executor, state=StateSnapshot(), context=_make_context())
    )


def _executor(journal: HashChainJournal) -> ToolExecutor:
    return ToolExecutor(
        registry=build_default_registry(),
        clock=DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)),
        journal=journal,
        provider=FixtureFlightProvider(),
    )


def _wire_completion(message: dict[str, Any], finish_reason: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-loop",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }


def test_record_then_replay_reproduces_trajectory_without_network(tmp_path: Path) -> None:
    """Record through the real Chat Completions client (mocked transport), replay offline."""
    task = AgentTask(
        task_id="t1",
        scenario_id="s1",
        public_request="What is the status of AS142 on 2026-07-28?",
        allowed_tools=["flight.get_status"],
    )
    wire_requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        wire_requests.append(body)
        if len(wire_requests) == 1:
            return httpx.Response(
                200,
                json=_wire_completion(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_status",
                                "type": "function",
                                "function": {
                                    "name": "flight__get_status",
                                    "arguments": json.dumps(
                                        {"flight_id": "AS142", "operating_day": "2026-07-28"}
                                    ),
                                },
                            }
                        ],
                    },
                    "tool_calls",
                ),
            )
        return httpx.Response(
            200,
            json=_wire_completion(
                {"role": "assistant", "content": "Flight AS142 is on time."}, "stop"
            ),
        )

    async def record() -> AgentRunResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = OpenAIChatCompletionsClient(
                api_key="sk-test",
                mode="record",
                record_dir=tmp_path,
                base_url="http://fake-openai.local/v1",
                http_client=http_client,
            )
            agent = ModelToolCallingAgent(model_client=client)
            return await agent.execute(
                task=task,
                executor=_executor(record_journal),
                state=StateSnapshot(),
                context=_make_context(),
            )

    record_journal = HashChainJournal()
    recorded = asyncio.run(record())
    assert recorded.stop_reason == AgentStopReason.COMPLETED, recorded.warnings
    assert recorded.final_response == "Flight AS142 is on time."
    assert len(wire_requests) == 2
    assert model_exchange_manifest_path(tmp_path, "s1", str(RUN_ID)).is_file()

    replay_journal = HashChainJournal()
    replayed = _execute(ReplayModelClient.from_directory(tmp_path), task, _executor(replay_journal))

    assert replayed.stop_reason == AgentStopReason.COMPLETED, replayed.warnings
    assert replayed.final_response == "Flight AS142 is on time."
    assert replayed.tool_call_count == 1
    assert replayed.model_exchange_digest == recorded.model_exchange_digest
    assert replay_journal.final_digest() == record_journal.final_digest()
    assert len(wire_requests) == 2  # replay performed zero network calls


def test_registered_tool_outside_task_allowlist_is_denied_by_executor() -> None:
    task = AgentTask(
        task_id="t-hidden",
        scenario_id="s-hidden",
        public_request="Check the flight.",
        allowed_tools=["flight.get_status"],
    )
    journal = HashChainJournal()
    client = ScriptedClient(
        [
            ModelResponse(
                content=None,
                tool_calls=[
                    ModelToolCall(
                        call_id="hidden-1",
                        tool_name="policy.get_rebooking_rules",
                        arguments={},
                    )
                ],
                finish_reason="tool_calls",
            ),
            ModelResponse(content="Unable to access that tool.", finish_reason="stop"),
        ]
    )
    result = _execute(client, task, _executor(journal))

    assert result.stop_reason == AgentStopReason.COMPLETED
    assert result.tool_call_count == 1
    assert result.invalid_tool_call_count == 1
    tool_calls = [entry for entry in journal.entries if entry.type == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["authorization_decision"] == "denied"


def test_agent_task_cannot_broaden_runner_installed_execution_policy() -> None:
    """A model task is not allowed to replace the runner's scenario policy."""
    context = _make_context()
    journal = HashChainJournal()
    env = SimulatedAirlineEnvironment()
    executor = ToolExecutor(
        registry=build_transactional_registry(env),
        clock=context.clock,
        journal=journal,
        provider=FixtureFlightProvider(),
        execution_policy=ExecutionToolPolicy(
            scenario_id=context.scenario_id,
            allowed_tool_names=("booking.get_current",),
            allowed_mutation_classes=("read_only",),
        ),
    )
    task = AgentTask(
        task_id="t-broaden",
        scenario_id=context.scenario_id,
        public_request="Send an update.",
        allowed_tools=["notification.send_simulated"],
        scenario_mode="transactional",
    )
    client = ScriptedClient(
        [
            ModelResponse(
                content=None,
                tool_calls=[
                    ModelToolCall(
                        call_id="broaden-1",
                        tool_name="notification.send_simulated",
                        arguments={
                            "passenger_name": "Jane Doe",
                            "message": "unsafe",
                            "idempotency_key": "blocked-notification",
                        },
                    )
                ],
                finish_reason="tool_calls",
            ),
            ModelResponse(content="Done.", finish_reason="stop"),
        ]
    )
    result = _execute(client, task, executor)

    assert result.invalid_tool_call_count == 1
    assert env.notifications == []
    assert executor.execution_policy is not None
    assert executor.execution_policy.allowed_tool_names == ("booking.get_current",)
    assert journal.entries[0].payload["authorization_decision"] == "denied"

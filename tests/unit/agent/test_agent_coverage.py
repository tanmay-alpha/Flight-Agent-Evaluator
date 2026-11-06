"""Coverage tests for agent loop, prompt, and security modules."""

from __future__ import annotations

import asyncio
import datetime
import uuid

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.agent.security import redact_secrets, scan_request_for_reference_leakage
from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    PromptPolicy,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_default_registry


class ScriptedModelClient:
    """Deterministic model double returning scripted responses and capturing requests."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []

    @property
    def provider(self) -> str:
        return "scripted"

    def begin_run(
        self, *, scenario_id: str, run_id: str, configuration: ModelConfiguration,
        prompt_digest: str | None = None,
    ) -> None:
        self._run = (scenario_id, run_id, configuration)

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self._responses.pop(0)

    async def end_run(self) -> ModelExchangeManifest:
        scenario_id, run_id, configuration = self._run
        return ModelExchangeManifest(
            manifest_id=f"{scenario_id}__{run_id}", model_configuration=configuration
        )


def _tool_response(*calls: ModelToolCall) -> ModelResponse:
    return ModelResponse(
        role="assistant", content=None, tool_calls=list(calls), finish_reason="tool_calls"
    )


def _make_context(tool_call_limit: int = 5) -> RunContext:
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    id_factory = DeterministicIdFactory(scenario_id="test", scenario_version=1, seed=42)
    return RunContext(
        run_id=uuid.uuid4(),
        scenario_id="test",
        scenario_version=1,
        seed=42,
        clock=clock,
        id_factory=id_factory,
        tool_call_limit=tool_call_limit,
        time_limit_seconds=60,
        correlation_id="c1",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


def _run(
    client: ScriptedModelClient, task: AgentTask, tool_call_limit: int = 5
) -> tuple[AgentRunResult, HashChainJournal]:
    context = _make_context(tool_call_limit)
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry=build_default_registry(),
        clock=context.clock,
        journal=journal,
        provider=FixtureFlightProvider(),
        tool_call_limit=tool_call_limit,
    )
    agent = ModelToolCallingAgent(model_client=client, prompt_policy=get_default_prompt_policy())
    res = asyncio.run(
        agent.execute(task=task, executor=executor, state=StateSnapshot(), context=context)
    )
    return res, journal


def test_prompt_policy_canonical_digest() -> None:
    p = PromptPolicy(policy_id="test_p", version="1.0.0", content="Test prompt content")
    digest = p.canonical_digest()
    assert len(digest) == 64
    default_p = get_default_prompt_policy()
    assert len(default_p.canonical_digest()) == 64


def test_model_configuration_canonical_digest() -> None:
    cfg = ModelConfiguration(provider="openai", model_id="gpt-4o-mini", temperature=0.0)
    assert len(cfg.canonical_digest()) == 64


def test_model_exchange_manifest_digest() -> None:
    cfg = ModelConfiguration()
    manifest = ModelExchangeManifest(manifest_id="m1", model_configuration=cfg, exchanges=[])
    assert len(manifest.manifest_digest()) == 64


def test_invalid_arguments_are_journaled_and_charged_to_tool_budget() -> None:
    """Regression: client-side validation used to hide invalid calls from the journal/budget."""
    task = AgentTask(
        task_id="t1",
        scenario_id="test",
        public_request="Query status",
        allowed_tools=["flight.get_status"],
        max_turns=5,
        tool_call_limit=2,
    )
    client = ScriptedModelClient(
        [
            _tool_response(ModelToolCall(call_id="c1", tool_name="flight.get_status")),
            _tool_response(ModelToolCall(call_id="c2", tool_name="flight.get_status")),
            ModelResponse(role="assistant", content="unreachable"),
        ]
    )
    res, journal = _run(client, task, tool_call_limit=2)

    tool_calls = [e for e in journal.entries if e.type == "tool_call"]
    tool_results = [e for e in journal.entries if e.type == "tool_result"]
    assert [e.payload["tool_name"] for e in tool_calls] == ["flight.get_status"] * 2
    assert [r.payload["error"]["error_type"] for r in tool_results] == ["invalid_arguments"] * 2
    assert res.tool_call_count == 2
    assert res.invalid_tool_call_count == 2
    assert res.stop_reason == AgentStopReason.TOOL_LIMIT_EXCEEDED


def test_unknown_tool_and_invalid_arguments_are_counted_invalid() -> None:
    task = AgentTask(
        task_id="t1",
        scenario_id="test",
        public_request="Query status",
        allowed_tools=["flight.get_status"],
        max_turns=5,
        tool_call_limit=5,
    )
    client = ScriptedModelClient(
        [
            _tool_response(ModelToolCall(call_id="c1", tool_name="unknown_tool_x")),
            _tool_response(ModelToolCall(call_id="c2", tool_name="flight.get_status")),
            ModelResponse(role="assistant", content="Could not find flight."),
        ]
    )
    res, journal = _run(client, task)

    assert res.stop_reason == AgentStopReason.COMPLETED
    assert res.invalid_tool_call_count == 2
    assert res.model_exchange_digest is not None
    # The model sees the executor's authoritative rejection, not a client-side message.
    assert "input schema" in client.requests[2].messages[-1]["content"]


def test_empty_allowlist_exposes_no_tools() -> None:
    """Regression: an empty allowlist used to expose every registered tool to the model."""
    task = AgentTask(
        task_id="t1",
        scenario_id="test",
        public_request="Query status",
        allowed_tools=[],
        max_turns=1,
    )
    client = ScriptedModelClient([ModelResponse(role="assistant", content="No tools.")])
    _run(client, task)
    assert client.requests[0].tools == []


def test_security_redaction_edge_cases() -> None:
    assert redact_secrets(None) is None
    assert redact_secrets(123) == 123
    assert redact_secrets(("a", "b")) == ("a", "b")
    empty_scan = scan_request_for_reference_leakage(
        ModelRequest(
            model_id="m",
            prompt_policy_id="p",
            prompt_policy_version="1",
            prompt_digest="d",
            turn_index=0,
            messages=[],
            model_configuration=ModelConfiguration(),
        ),
        ["", "a"],
    )
    assert len(empty_scan) == 0

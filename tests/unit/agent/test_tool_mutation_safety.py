"""Unit tests verifying that model mutation tool attempts trigger safety violations."""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import Any

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.contracts.model import (
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import ToolDefinition, ToolHandler, ToolRegistry


def _make_context() -> RunContext:
    clock = DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    id_factory = DeterministicIdFactory(scenario_id="test", scenario_version=1, seed=42)
    return RunContext(
        run_id=uuid.uuid4(),
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


class DummyMutationHandler(ToolHandler):
    tool_name = "booking.confirm"
    tool_definition = ToolDefinition(
        name="booking.confirm",
        description="Confirm booking mutation",
        input_schema={"type": "object", "properties": {}},
        mutation_class="simulated_mutation",
    )

    async def execute(
        self, arguments: dict[str, Any], provider: Any, context: RunContext
    ) -> dict[str, Any]:
        return {"status": "mutated"}


class MutatingClient:
    provider = "scripted"

    def begin_run(
        self, *, scenario_id: str, run_id: str, configuration: ModelConfiguration,
        prompt_digest: str | None = None,
    ) -> None:
        self._manifest = ModelExchangeManifest(
            manifest_id=f"{scenario_id}__{run_id}", model_configuration=configuration
        )

    async def create_completion(self, request: ModelRequest) -> ModelResponse:  # noqa: ARG002
        return ModelResponse(
            role="assistant",
            content=None,
            tool_calls=[ModelToolCall(call_id="call-mut-1", tool_name="booking.confirm")],
            finish_reason="tool_calls",
        )

    async def end_run(self) -> ModelExchangeManifest:
        return self._manifest


def test_model_agent_mutation_attempt_triggers_safety_violation() -> None:
    registry = ToolRegistry()
    registry.register(DummyMutationHandler())
    task = AgentTask(
        task_id="t1",
        scenario_id="s1",
        public_request="Confirm booking",
        allowed_tools=["booking.confirm"],
    )
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry=registry,
        clock=DeterministicVirtualClock(datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)),
        journal=journal,
        provider=FixtureFlightProvider(),
    )

    result = asyncio.run(
        ModelToolCallingAgent(model_client=MutatingClient()).execute(
            task=task, executor=executor, state=StateSnapshot(), context=_make_context()
        )
    )

    assert result.stop_reason == AgentStopReason.SAFETY_VIOLATION
    assert any("Safety Violation" in w for w in result.warnings)
    denied = [e for e in journal.entries if e.type == "tool_call"]
    assert denied[0].payload["authorization_decision"] == "denied"

"""Protocols for agent policies and provider-neutral model clients."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentTask,
    ModelRequest,
    ModelResponse,
)
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot


@runtime_checkable
class AgentPolicy(Protocol):
    """Protocol for benchmark agents (Oracle, Baseline, Model-driven)."""

    @property
    def agent_id(self) -> str:
        """Unique agent identifier."""
        ...

    @property
    def agent_version(self) -> str:
        """Version string of the agent policy."""
        ...

    async def execute(
        self,
        task: AgentTask,
        executor: ToolExecutor,
        state: StateSnapshot,
        context: RunContext,
    ) -> AgentRunResult:
        """Execute the agent task through the evaluator's ToolExecutor boundary."""
        ...


@runtime_checkable
class ModelClient(Protocol):
    """Provider-neutral model client protocol."""

    @property
    def provider(self) -> str:
        """Model provider name (e.g., 'openai', 'replay')."""
        ...

    @property
    def model_id(self) -> str:
        """Model identifier (e.g., 'gpt-4o-mini')."""
        ...

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        """Create a completion response for a given model request."""
        ...

    def reset(self) -> None:
        """Reset internal turn counters or state if necessary."""
        ...

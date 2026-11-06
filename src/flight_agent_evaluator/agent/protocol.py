"""Protocols for agent policies and provider-neutral model clients."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentTask,
    ModelConfiguration,
    ModelExchangeManifest,
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
    """Provider-neutral model client protocol.

    A client is bound to one agent run at a time: ``begin_run`` selects (or
    resets) the exchange log for the run and ``end_run`` returns the run's
    :class:`ModelExchangeManifest`.
    """

    @property
    def provider(self) -> str:
        """Transport label for diagnostics only (never part of fingerprints)."""
        ...

    def begin_run(
        self,
        *,
        scenario_id: str,
        run_id: str,
        configuration: ModelConfiguration,
        prompt_digest: str | None = None,
    ) -> None:
        """Start a run; replay clients load and verify the run's recorded manifest."""
        ...

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        """Create a completion response for a given model request."""
        ...

    async def end_run(self) -> ModelExchangeManifest:
        """Finish the run and return its exchange manifest (record mode persists it)."""
        ...

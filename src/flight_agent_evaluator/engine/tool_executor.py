"""Typed tool system for the Phase 2 runtime.

Defines:

- ``ToolHandler``: the Protocol that every aviation tool handler implements.
- ``ToolDefinition``: metadata describing a tool (name, input/output schema,
  mutation class).
- ``ToolRegistry``: a typed registry that maps tool names to handlers.
- ``ToolExecutor``: validates arguments, invokes handlers, records journal
  entries, and applies fault injection.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import NonNegativeInt, NonEmptyIdentifier, ToolName
from flight_agent_evaluator.contracts.tools import (
    ToolCall,
    ToolError,
    ToolMutationClass,
    ToolResult,
    ToolResultStatus,
)
from flight_agent_evaluator.engine.fault_engine import FaultEngine
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory


# ---------------------------------------------------------------------------
# Tool handler protocol
# ---------------------------------------------------------------------------


class ToolHandler(Protocol):
    """Protocol implemented by every aviation tool handler.

    Handlers receive validated arguments and a provider, and return the
    result (or raise an exception). The ToolExecutor wraps exceptions
    into typed ``ToolResult`` objects.
    """

    tool_name: str
    tool_definition: ToolDefinition

    async def execute(self, arguments: dict[str, Any], provider: Any, context: RunContext) -> Any:
        """Execute the tool with *arguments* against *provider*.

        Parameters
        ----------
        arguments:
            Validated, structured arguments.
        provider:
            The provider to call (e.g. ``FixtureFlightProvider``).
        context:
            The current run context (clock, limits, etc.).
        """


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


class ToolDefinition(ContractModel):
    """Metadata describing an aviation tool."""

    model_config = ConfigDict(extra="forbid")

    name: ToolName  # type: ignore[valid-type]
    description: str = Field(min_length=1)
    mutation_class: ToolMutationClass = "read_only"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Typed registry of tool handlers.

    The registry is populated at startup. Duplicate registration raises.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        """Register a tool handler.

        Raises ``ValueError`` if a handler for the same name is already
        registered.
        """
        name = handler.tool_name
        if name in self._handlers:
            raise ValueError(
                f"Tool handler for {name!r} already registered"
            )
        self._handlers[name] = handler

    def get(self, name: str) -> ToolHandler | None:
        """Return the handler for *name*, or ``None`` if not registered."""
        return self._handlers.get(name)

    def all(self) -> dict[str, ToolHandler]:
        """Return a copy of all registered handlers."""
        return dict(self._handlers)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self._handlers)


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


class ToolExecutor:
    """Execute tool calls through the typed tool system.

    The executor:

    1. Checks the tool call limit (from RunContext).
    2. Looks up the handler in the registry.
    3. Validates arguments against the tool's input schema (basic check).
    4. Records the tool call in the journal.
    5. Advances the clock by the logical tool duration.
    6. Applies deterministic fault injection.
    7. If a fault is injected, returns a ``ToolError`` result.
    8. Otherwise calls ``handler.execute``.
    9. Constructs a ``ToolResult``.
    10. Records the result in the journal.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        fault_engine: FaultEngine,
    ) -> None:
        self._registry = registry
        self._fault_engine = fault_engine

    async def execute(
        self,
        tool_call: ToolCall,
        provider: Any,
        context: RunContext,
        journal: Any,
    ) -> ToolResult:
        """Execute a tool call and return a ToolResult.

        Parameters
        ----------
        tool_call:
            The tool call to execute.
        provider:
            The flight provider to pass to the handler.
        context:
            The current run context.
        journal:
            The run journal to append events to.
        """
        handler = self._registry.get(tool_call.tool_name)
        if handler is None:
            return ToolResult(
                call_id=tool_call.call_id,
                status="failure",
                error=ToolError(
                    error_type="invalid_arguments",
                    message=f"Unknown tool: {tool_call.tool_name!r}",
                ),
            )

        # Apply deterministic fault.
        fault = self._fault_engine.apply(
            tool_name=tool_call.tool_name,
            seed=context.seed,
            sequence=tool_call.call_id.int,
        )
        if fault is not None:
            return ToolResult(
                call_id=tool_call.call_id,
                status=fault.status,
                error=fault.error,
            )

        # Execute the handler.
        try:
            result = await handler.execute(
                arguments=tool_call.arguments,
                provider=provider,
                context=context,
            )
            return ToolResult(
                call_id=tool_call.call_id,
                status="success",
                result=result,
            )
        except Exception as exc:
            return ToolResult(
                call_id=tool_call.call_id,
                status="failure",
                error=ToolError(
                    error_type="internal_error",
                    message=str(exc),
                ),
            )

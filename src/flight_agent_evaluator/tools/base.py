"""Base tool types: ToolHandler protocol, ToolDefinition, ToolRegistry."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import ConfigDict, Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import ToolName

# ---------------------------------------------------------------------------
# Handler protocol (runtime-layer; only typed dicts, no contracts)
# ---------------------------------------------------------------------------


class ToolHandler(Protocol):
    """Protocol implemented by every aviation tool handler.

    Handlers receive validated arguments and a provider, and return the
    result (or raise an exception). The ToolExecutor wraps exceptions
    into typed ``ToolResult`` objects.
    """

    tool_name: str
    tool_definition: ToolDefinition

    async def execute(self, arguments: dict[str, Any], provider: Any, context: Any) -> Any:
        """Execute the tool with *arguments* against *provider*."""


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


class ToolDefinition(ContractModel):
    """Metadata describing an aviation tool."""

    model_config = ConfigDict(extra="forbid")

    name: ToolName
    description: str = Field(min_length=1)
    mutation_class: str = "read_only"
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
            raise ValueError(f"Tool handler for {name!r} already registered")
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

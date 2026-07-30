"""Base tool types: ToolHandler protocol, ToolDefinition, ToolRegistry.

The authoritative tool-system types live in this module. The
``ToolExecutor`` and the aviation tool handlers all consume these
definitions. The registry rejects duplicate tool names and unknown
tools produce typed ``ToolResult`` failures.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import ConfigDict, Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.common import ToolName
from flight_agent_evaluator.contracts.tools import ToolMutationClass
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.runtime.context import RunContext


# ---------------------------------------------------------------------------
# Handler protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolHandler(Protocol):
    """Protocol implemented by every aviation tool handler.

    Handlers receive validated, typed arguments together with a
    :class:`FlightProvider` and the current :class:`RunContext`. They
    return a JSON-compatible result, or raise an exception that the
    executor wraps into a typed :class:`ToolError`.

    The runtime layer never instantiates raw ``dict`` handlers: every
    implementation must declare ``tool_name`` and ``tool_definition``
    and implement an ``async`` :meth:`execute` coroutine.
    """

    tool_name: str
    tool_definition: ToolDefinition

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,
        context: RunContext,
    ) -> Any:
        """Execute the tool with validated *arguments* against *provider*."""


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


class ToolDefinition(ContractModel):
    """Metadata describing an aviation tool.

    The mutation class is a strict ``ToolMutationClass`` literal drawn
    from :mod:`contracts.tools`, not a free-form string. The input and
    output schemas follow the JSON Schema vocabulary and are validated
    by the executor.
    """

    model_config = ConfigDict(extra="forbid")

    name: ToolName  # type: ignore[valid-type]
    description: str = Field(min_length=1)
    mutation_class: ToolMutationClass = "read_only"
    input_schema: dict[str, Any] = Field(default_factory=dict)  # type: ignore[valid-type]
    output_schema: dict[str, Any] = Field(default_factory=dict)  # type: ignore[valid-type]


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


class DuplicateToolRegistrationError(ValueError):
    """Raised when registering two handlers for the same tool name."""


class UnknownToolError(KeyError):
    """Raised when looking up a tool that is not registered."""


class ToolRegistry:
    """Typed registry of tool handlers.

    The registry is populated at startup. Duplicate registration raises.
    The registry intentionally exposes only dict-style accessors — its
    handlers are not exposed externally.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, handler: ToolHandler) -> None:
        """Register a tool handler.

        Raises :class:`DuplicateToolRegistrationError` if a handler for
        the same name is already registered.
        """
        name = handler.tool_name
        if name in self._handlers:
            raise DuplicateToolRegistrationError(
                f"Tool handler for {name!r} already registered"
            )
        self._handlers[name] = handler
        self._definitions[name] = handler.tool_definition

    def get(self, name: str) -> ToolHandler:
        """Return the handler for *name*.

        Raises :class:`UnknownToolError` when the tool is not
        registered. Errors at runtime use the registry as the single
        source of truth — there are no silent fallbacks.
        """
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise UnknownToolError(f"Unknown tool: {name!r}") from exc

    def try_get(self, name: str) -> ToolHandler | None:
        """Return the handler for *name* or ``None`` if not registered."""
        return self._handlers.get(name)

    def definition_for(self, name: str) -> ToolDefinition | None:
        """Return the metadata for *name* or ``None`` if not registered."""
        return self._definitions.get(name)

    def tool_names(self) -> tuple[str, ...]:
        """Return a tuple of all registered tool names."""
        return tuple(self._handlers)

    def __contains__(self, name: str) -> bool:
        return name in self._handlers


__all__ = [
    "DuplicateToolRegistrationError",
    "ToolDefinition",
    "ToolHandler",
    "ToolRegistry",
    "UnknownToolError",
]

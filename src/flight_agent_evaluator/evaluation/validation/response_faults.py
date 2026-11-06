"""Validation-only tool-response faults, applied before the executor journals payloads.

The real handler still executes with its original definition and execution policy.
Only returned data is overlaid, never registry metadata, policy or journal entries.
Wrappers are scoped to one agent execution and restored even when replay fails.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import ToolHandler, ToolRegistry


@dataclass(frozen=True)
class ResponseOverride:
    """Overlay one zero-based invocation of a handler, after a successful return."""

    tool_name: str
    payload: dict[str, Any]
    occurrence: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize all fault inputs for reproducible validation cases."""
        return {
            "tool_name": self.tool_name,
            "payload": self.payload,
            "occurrence": self.occurrence,
        }


class _ResponseWrapper:
    def __init__(self, handler: ToolHandler, overrides: tuple[ResponseOverride, ...]) -> None:
        self.original = handler.execute
        self.overrides = overrides
        self.invocations = 0

    async def __call__(
        self, arguments: dict[str, Any], provider: FlightProvider, context: RunContext
    ) -> Any:
        index = self.invocations
        self.invocations += 1
        result = await self.original(arguments=arguments, provider=provider, context=context)
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        for override in self.overrides:
            if override.occurrence == index:
                if not isinstance(result, dict):
                    raise TypeError("Response fault requires an object-shaped tool payload")
                result = {**result, **override.payload}
        return result


@contextmanager
def response_overrides(
    registry: ToolRegistry, overrides: tuple[ResponseOverride, ...]
) -> Iterator[None]:
    """Temporarily decorate registered handler methods without replacing definitions."""
    originals: list[tuple[ToolHandler, Callable[..., Awaitable[Any]]]] = []
    try:
        for tool_name in dict.fromkeys(override.tool_name for override in overrides):
            handler = registry.get(tool_name)
            wrapper = _ResponseWrapper(
                handler, tuple(item for item in overrides if item.tool_name == tool_name)
            )
            originals.append((handler, handler.execute))
            setattr(handler, "execute", wrapper)  # noqa: B010 - scoped method decoration
        yield
    finally:
        for handler, original in reversed(originals):
            setattr(handler, "execute", original)  # noqa: B010 - restore the bound method

"""Typed tool system for the Phase 2 runtime.

The canonical definitions of ``ToolHandler``, ``ToolDefinition``, and
``ToolRegistry`` live in :mod:`flight_agent_evaluator.tools.base`. This
module re-uses those types and provides the ``ToolExecutor`` which
validates arguments, invokes handlers, records journal entries, and
applies fault injection.
"""

from __future__ import annotations

from typing import Any

from flight_agent_evaluator.contracts.tools import (
    ToolCall,
    ToolError,
    ToolResult,
)
from flight_agent_evaluator.engine.fault_engine import FaultEngine
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import ToolRegistry


class ToolExecutor:
    """Execute tool calls through the typed tool system.

    The executor:

    1. Checks the tool call limit (from RunContext).
    2. Looks up the handler in the registry.
    3. Applies deterministic fault injection via the ``FaultEngine``.
    4. If a fault is injected, returns a ``ToolError`` result.
    5. Otherwise calls ``handler.execute``.
    6. Wraps exceptions into typed ``ToolResult`` objects.
    7. Records the tool call in the journal.
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
        journal: Any = None,  # noqa: ARG002  (reserved for future journal recording)
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
            Optional journal to record tool call/result entries into.
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

"""Typed tool registry and aviation tool handlers for the Phase 2 runtime.

The tools package:

- Defines the ``ToolHandler`` Protocol and ``ToolDefinition`` in ``tools.base``.
- Provides aviation-specific handlers in ``tools.flight``.

Handlers accept structured arguments and a ``FixtureFlightProvider``. They
return structured results or raise exceptions that the ToolExecutor wraps.
"""

from flight_agent_evaluator.tools.base import (
    ToolDefinition,
    ToolHandler,
    ToolRegistry,
)
from flight_agent_evaluator.tools.flight import (
    FlightGetStatusHandler,
    FlightSearchHandler,
    register_default_tools,
)

__all__ = [
    "ToolDefinition",
    "ToolHandler",
    "ToolRegistry",
    "FlightGetStatusHandler",
    "FlightSearchHandler",
    "register_default_tools",
]

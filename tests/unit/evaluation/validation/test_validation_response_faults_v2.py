"""Response perturbations operate before journaling and restore real handlers."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from flight_agent_evaluator.evaluation.validation.response_faults import (
    ResponseOverride,
    response_overrides,
)
from flight_agent_evaluator.providers.base import FlightProvider
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.tools.base import ToolDefinition, ToolRegistry


class _Handler:
    tool_name = "policy.get_rebooking_rules"

    def __init__(self) -> None:
        self.tool_definition = ToolDefinition(name=self.tool_name, description="Test policy reader")

    async def execute(
        self,
        arguments: dict[str, Any],
        provider: FlightProvider,
        context: RunContext,
    ) -> dict[str, Any]:
        return {"status": "unchanged", "carrier_code": arguments["carrier_code"]}


def test_overlay_affects_selected_invocation_only_and_preserves_metadata() -> None:
    handler = _Handler()
    registry = ToolRegistry()
    registry.register(handler)
    definition = registry.definition_for(handler.tool_name)
    original = handler.execute
    provider = cast(FlightProvider, object())
    context = cast(RunContext, object())
    override = ResponseOverride(handler.tool_name, {"metadata": {"notes": ["instruction"]}})
    with response_overrides(registry, (override,)):
        first = asyncio.run(handler.execute({"carrier_code": "AS"}, provider, context))
        second = asyncio.run(handler.execute({"carrier_code": "AS"}, provider, context))
        assert first["metadata"] == {"notes": ["instruction"]}
        assert first["status"] == "unchanged"
        assert "metadata" not in second
        assert registry.definition_for(handler.tool_name) is definition
    assert handler.execute == original


def test_decorated_handler_is_restored_when_replay_raises() -> None:
    handler = _Handler()
    registry = ToolRegistry()
    registry.register(handler)
    original = handler.execute
    with (
        pytest.raises(RuntimeError, match="interrupted"),
        response_overrides(registry, (ResponseOverride(handler.tool_name, {"status": "changed"}),)),
    ):
        raise RuntimeError("interrupted")
    assert handler.execute == original

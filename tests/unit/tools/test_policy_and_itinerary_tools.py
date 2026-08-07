"""Unit tests for policy.get_rebooking_rules and itinerary.get_current_booking tools."""

from __future__ import annotations

import asyncio
import datetime
import uuid

from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.tools.itinerary import ItineraryGetCurrentBookingHandler
from flight_agent_evaluator.tools.policy import PolicyGetRebookingRulesHandler


def _make_context():
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


def test_policy_get_rebooking_rules_handler():
    handler = PolicyGetRebookingRulesHandler()
    assert handler.tool_name == "policy.get_rebooking_rules"
    assert handler.tool_definition.mutation_class == "read_only"

    provider = FixtureFlightProvider()
    context = _make_context()
    res = asyncio.run(
        handler.execute(arguments={"carrier_code": "AS"}, provider=provider, context=context)
    )
    assert res["carrier_code"] == "AS"
    assert "max_delay_hours_for_refund" in res


def test_itinerary_get_current_booking_handler():
    handler = ItineraryGetCurrentBookingHandler()
    assert handler.tool_name == "itinerary.get_current_booking"
    assert handler.tool_definition.mutation_class == "read_only"

    provider = FixtureFlightProvider()
    context = _make_context()
    res = asyncio.run(
        handler.execute(
            arguments={"booking_reference": "PNR123"}, provider=provider, context=context
        )
    )
    assert res["booking_reference"] == "PNR123"
    assert "passenger_name" in res

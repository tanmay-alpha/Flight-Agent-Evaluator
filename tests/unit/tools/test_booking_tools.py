"""Unit tests for simulated booking tools."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.environment.errors import StateTransitionError
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.tools.booking_tools import (
    ApprovalGetStatusHandler,
    ApprovalRequestHandler,
    BookingConfirmRebookingHandler,
    BookingGetCurrentHandler,
    BookingHoldAlternativeHandler,
    BookingReleaseHoldHandler,
    NotificationSendSimulatedHandler,
)


def _make_context(now: datetime) -> RunContext:
    clock = DeterministicVirtualClock(now)
    id_factory = DeterministicIdFactory("test", 1, 42)
    return RunContext(
        run_id=uuid.uuid4(),
        scenario_id="test",
        scenario_version=1,
        seed=42,
        clock=clock,
        id_factory=id_factory,
        tool_call_limit=10,
        time_limit_seconds=60,
        correlation_id="c1",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


def test_booking_tools_execution() -> None:
    env = SimulatedAirlineEnvironment()
    provider = FixtureFlightProvider()
    now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)
    ctx = _make_context(now)

    # 1. get_current
    get_handler = BookingGetCurrentHandler(env)
    res1 = asyncio.run(get_handler.execute({"booking_reference": "AS-1001"}, provider, ctx))
    assert res1["booking_reference"] == "AS-1001"
    assert res1["status"] == "disrupted"

    # 2. hold_alternative
    hold_handler = BookingHoldAlternativeHandler(env)
    hold_res = asyncio.run(
        hold_handler.execute(
            {
                "booking_reference": "AS-1001",
                "offer_id": "offer-alt-1",
                "flight_number": "AS144",
                "origin": "JFK",
                "destination": "LHR",
                "price_amount": 550.0,
                "idempotency_key": "key-hold-tool-1",
            },
            provider,
            ctx,
        )
    )
    hold_id = hold_res["hold_id"]

    # 3. request approval tool
    req_handler = ApprovalRequestHandler(env)
    req_res = asyncio.run(
        req_handler.execute(
            {
                "booking_reference": "AS-1001",
                "action_type": "confirm_rebooking",
                "offer_id": "offer-alt-1",
                "reason": "Passenger disruption.",
                "idempotency_key": "key-appr-req-1",
            },
            provider,
            ctx,
        )
    )
    assert req_res["status"] == "approved"

    # 4. confirm_rebooking
    confirm_handler = BookingConfirmRebookingHandler(env)
    res2 = asyncio.run(
        confirm_handler.execute(
            {
                "booking_reference": "AS-1001",
                "hold_id": hold_id,
                "approval_id": req_res["approval_id"],
                "idempotency_key": "key-confirm-tool-1",
            },
            provider,
            ctx,
        )
    )
    assert res2["status"] == "confirmed"

    # 5. get_status
    appr_handler = ApprovalGetStatusHandler(env)
    res3 = asyncio.run(appr_handler.execute({"approval_id": req_res["approval_id"]}, provider, ctx))
    assert res3["approval_id"] == req_res["approval_id"]

    # 6. release_hold tool
    rel_handler = BookingReleaseHoldHandler(env)
    with pytest.raises(StateTransitionError):
        asyncio.run(
            rel_handler.execute(
                {"hold_id": hold_id, "idempotency_key": "key-rel-tool-1"}, provider, ctx
            )
        )

    # 7. notification
    notif_handler = NotificationSendSimulatedHandler()
    res4 = asyncio.run(
        notif_handler.execute(
            {
                "passenger_name": "Jane Doe",
                "message": "Rebooking confirmed.",
                "idempotency_key": "key-notif-1",
            },
            provider,
            ctx,
        )
    )
    assert res4["status"] == "sent"

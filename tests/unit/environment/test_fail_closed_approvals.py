"""Approvals fail closed unless a scenario explicitly configures a decision (C3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario, ScenarioEnvironment
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.environment.errors import ResourceNotFoundError
from flight_agent_evaluator.environment.fixtures import get_default_environment_setup

NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
TRANSACTIONAL_DIR = Path("resources/scenarios/transactional")

_BOOKING = {
    "booking_reference": "ZZ-9001",
    "passenger_name": "SYNTHETIC_PASSENGER",
    "current_flight_number": "AA100",
    "origin": "JFK",
    "destination": "LHR",
    "scheduled_departure": "2026-08-13T00:00:00+00:00",
}
_OFFER = {
    "offer_id": "offer-zz-1",
    "flight_number": "AS900",
    "origin": "JFK",
    "destination": "LHR",
    "price_amount": 500.0,
}


def _scenario(environment: dict[str, Any] | None) -> BenchmarkScenario:
    data = json.loads((TRANSACTIONAL_DIR / "approval-granted.json").read_text(encoding="utf-8"))
    data["scenario_id"] = {"id": "never-configured-scenario", "version": 1}
    if environment is None:
        data.pop("environment")
    else:
        data["environment"] = environment
    return BenchmarkScenario.model_validate(data)


def _request_approval(env: SimulatedAirlineEnvironment, booking: str, offer: dict[str, Any]) -> str:
    hold = env.place_hold(
        booking_reference=booking,
        offer_id=offer["offer_id"],
        flight_number=offer["flight_number"],
        origin=offer["origin"],
        destination=offer["destination"],
        price_amount=offer["price_amount"],
        idempotency_key="hold-1",
        current_time=NOW,
    )
    result = env.request_approval(
        booking_reference=booking,
        action_type="confirm_rebooking",
        offer_id=offer["offer_id"],
        hold_id=str(hold["hold_id"]),
        reason="Please approve.",
        idempotency_key="approval-1",
        current_time=NOW,
    )
    return str(result["status"])


def test_bare_environment_denies_approval_requests() -> None:
    env = SimulatedAirlineEnvironment()
    offer = {
        "offer_id": "offer-alt-1",
        "flight_number": "AS144",
        "origin": "JFK",
        "destination": "LHR",
        "price_amount": 550.0,
    }
    assert _request_approval(env, "AS-1001", offer) == "denied"


def test_unknown_scenario_without_decision_is_not_approved() -> None:
    scenario = _scenario({"bookings": [_BOOKING], "offers": [_OFFER]})
    env = SimulatedAirlineEnvironment.from_scenario(scenario)
    assert _request_approval(env, "ZZ-9001", _OFFER) == "denied"


def test_explicit_decision_is_applied() -> None:
    scenario = _scenario(
        {"bookings": [_BOOKING], "offers": [_OFFER], "approval_decision": "pending"}
    )
    env = SimulatedAirlineEnvironment.from_scenario(scenario)
    assert _request_approval(env, "ZZ-9001", _OFFER) == "pending"


def test_scenario_without_environment_has_no_inventory() -> None:
    env = SimulatedAirlineEnvironment.from_scenario(_scenario(None))
    assert env.bookings == {}
    assert env.offers == {}
    with pytest.raises(ResourceNotFoundError):
        env.get_booking("AS-1001")


def test_environment_contains_exactly_declared_resources() -> None:
    env = SimulatedAirlineEnvironment.from_scenario(
        _scenario({"bookings": [_BOOKING], "offers": [_OFFER], "approval_decision": "approved"})
    )
    assert set(env.bookings) == {"ZZ-9001"}
    assert set(env.offers) == {"offer-zz-1"}


@pytest.mark.parametrize(
    "environment",
    [
        {"approval_decision": "maybe"},
        {"approval_status": "approved"},
        {"hold_expired": "yes"},
        {"bookings": [_BOOKING, _BOOKING]},
        {
            "offers": [_OFFER],
            "price_change_after_approval": {"offer_id": "nope", "new_price_amount": 1.0},
        },
        {"bookings": [{**_BOOKING, "status": "rebooked"}]},
    ],
)
def test_environment_block_is_strict(environment: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ScenarioEnvironment.model_validate(environment)


def test_environment_block_requires_transactional_mode() -> None:
    data = json.loads(Path("resources/scenarios/lax-sfo-ontime.json").read_text(encoding="utf-8"))
    data["environment"] = {"approval_decision": "approved"}
    with pytest.raises(ValidationError):
        BenchmarkScenario.model_validate(data)


def test_every_transactional_scenario_declares_its_environment() -> None:
    for path in sorted(TRANSACTIONAL_DIR.glob("*.json")):
        scenario = BenchmarkScenario.model_validate_json(path.read_text(encoding="utf-8"))
        assert scenario.environment is not None, path.name
        assert scenario.environment.bookings, path.name


def test_default_fixture_setup_is_unapproved_unless_requested() -> None:
    assert get_default_environment_setup().approval_decision is None
    assert get_default_environment_setup("approved").approval_decision == "approved"

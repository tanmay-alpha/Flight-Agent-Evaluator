"""Unit tests for tool registry builder functions."""

from flight_agent_evaluator.tools.base import (
    build_readonly_registry,
    build_registry_for_scenario,
    build_transactional_registry,
)


def test_build_registries():
    ro_reg = build_readonly_registry()
    assert "flight.get_status" in ro_reg

    tx_reg = build_transactional_registry()
    assert "booking.confirm_rebooking" in tx_reg
    assert "approval.request" in tx_reg

    class DummyScenario:
        scenario_mode = "transactional"

    dummy_tx = DummyScenario()
    reg_tx = build_registry_for_scenario(dummy_tx)
    assert "booking.confirm_rebooking" in reg_tx

    class DummyReadOnlyScenario:
        scenario_mode = "read_only"

    dummy_ro = DummyReadOnlyScenario()
    reg_ro = build_registry_for_scenario(dummy_ro)
    assert "booking.confirm_rebooking" not in reg_ro

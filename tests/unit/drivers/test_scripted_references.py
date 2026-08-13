"""Unit tests for JSON Pointer step references in ScriptedAgentDriver."""

import pytest

from flight_agent_evaluator.drivers.scripted import resolve_step_arguments


def test_resolve_step_arguments_dict_ref():
    prior = [{"hold_id": "hold-123", "price": {"amount": 550.0}}]
    args = {
        "hold_id": {"$ref_step": 0, "json_pointer": "/hold_id"},
        "amount": {"$ref_step": 0, "json_pointer": "/price/amount"},
        "static": "value",
    }
    resolved = resolve_step_arguments(args, prior)
    assert resolved["hold_id"] == "hold-123"
    assert resolved["amount"] == 550.0
    assert resolved["static"] == "value"


def test_resolve_step_arguments_string_ref():
    prior = [{"booking_ref": "AS-999"}]
    args = {"ref": "$ref:0/booking_ref"}
    resolved = resolve_step_arguments(args, prior)
    assert resolved["ref"] == "AS-999"


def test_resolve_step_arguments_nested_list():
    prior = [{"id": "item-1"}]
    args = {"items": [{"$ref_step": 0, "json_pointer": "/id"}]}
    resolved = resolve_step_arguments(args, prior)
    assert resolved["items"] == ["item-1"]


def test_resolve_step_arguments_out_of_range():
    with pytest.raises(ValueError):
        resolve_step_arguments({"ref": {"$ref_step": 5, "json_pointer": "/id"}}, [])

    with pytest.raises(ValueError):
        resolve_step_arguments({"ref": "$ref:5/id"}, [])


def test_resolve_step_arguments_missing_pointer():
    with pytest.raises(KeyError):
        resolve_step_arguments({"ref": {"$ref_step": 0, "json_pointer": "/nonexistent"}}, [{}])

    with pytest.raises(KeyError):
        resolve_step_arguments({"ref": "$ref:0/nonexistent"}, [{}])

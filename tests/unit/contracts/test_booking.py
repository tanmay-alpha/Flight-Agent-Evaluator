"""Tests for booking contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.contracts.base import Money
from flight_agent_evaluator.contracts.booking import (
    ApprovalDecision,
    ApprovalRequest,
    BookingReference,
    BookingSnapshot,
    IdempotencyKey,
    ScopedAction,
)


class TestBookingState:
    def test_valid_states_accepted(self) -> None:
        for state in ["hold", "confirmed", "cancelled", "expired", "ticketed"]:
            bs = BookingSnapshot(
                booking_reference=BookingReference(
                    record_locator="ABC123",
                    airline_iata="AA",
                ),
                state=state,
                flight_offers=(),
                passengers=(),
                total_price=_money(100, "USD"),
                currency="USD",
                created_at=datetime.now(UTC),
            )
            assert bs.state == state


class TestApprovalState:
    def test_valid_states(self) -> None:
        for state in ["pending", "granted", "denied", "expired"]:
            d = ApprovalDecision(
                request_id="r1",
                state=state,
                decided_at=datetime.now(UTC),
            )
            assert d.state == state


class TestBookingReference:
    def test_valid(self) -> None:
        r = BookingReference(record_locator="ABC123", airline_iata="AA")
        assert r.record_locator == "ABC123"
        assert r.airline_iata == "AA"

    def test_lowercase_airline_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BookingReference(record_locator="ABC123", airline_iata="aa")

    def test_one_char_airline_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BookingReference(record_locator="ABC123", airline_iata="A")


class TestScopedAction:
    def test_valid(self) -> None:
        a = ScopedAction(
            action="rebook",
            scope="booking",
            payload={"booking_id": "B1"},
        )
        assert a.action == "rebook"

    def test_blank_action_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScopedAction(action="", scope="booking", payload={})


class TestIdempotencyKey:
    def test_valid(self) -> None:
        k = IdempotencyKey(key="a" * 64, namespace="ns")
        assert k.key == "a" * 64
        assert k.namespace == "ns"

    def test_non_hex_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IdempotencyKey(key="g" * 64)

    def test_default_namespace(self) -> None:
        k = IdempotencyKey(key="a" * 64)
        assert k.namespace == "default"


class TestApprovalRequest:
    def test_valid(self) -> None:
        a = ApprovalRequest(
            request_id="req-1",
            proposed_action=ScopedAction(
                action="rebook",
                scope="booking",
                payload={"flight_id": "AS142"},
            ),
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC),
        )
        assert a.state == "pending"
        assert a.payload_hash is not None
        # payload_hash must match the canonical hash of the proposed_action payload
        from flight_agent_evaluator.canonical import canonical_hash

        expected_hash = canonical_hash({"flight_id": "AS142"})
        assert a.payload_hash == expected_hash

    def test_mismatched_payload_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ApprovalRequest(
                request_id="req-1",
                proposed_action=ScopedAction(
                    action="rebook",
                    scope="booking",
                    payload={"flight_id": "AS142"},
                ),
                payload_hash="a" * 64,  # wrong hash
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC),
            )


def _money(amount: int, currency: str) -> Money:
    return Money(amount=amount, currency=currency)

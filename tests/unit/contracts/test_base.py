"""Tests for base contract types."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.contracts.base import (
    ContractModel,
    Money,
    RawPayloadReference,
    SchemaVersion,
    SourceMetadata,
)


class TestMoney:
    def test_valid(self) -> None:
        m = Money(amount=100, currency="USD")
        assert m.amount == 100
        assert m.currency == "USD"

    def test_zero_amount_allowed(self) -> None:
        m = Money(amount=0, currency="USD")
        assert m.amount == 0

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=-1, currency="USD")

    def test_invalid_currency_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=0, currency="us")


class TestSchemaVersion:
    def test_valid(self) -> None:
        v = SchemaVersion(major=1, minor=2, patch=3)
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SchemaVersion(major=-1, minor=0, patch=0)


class TestRawPayloadReference:
    def test_valid(self) -> None:
        r = RawPayloadReference(
            uri="fixture://x.json",
            sha256="0" * 64,
        )
        assert r.sha256 == "0" * 64


class TestSourceMetadata:
    def test_valid(self) -> None:
        sm = SourceMetadata(
            provider_name="synthetic-fixture",
            provider_mode="fixture",
            source_observation_time=datetime(2026, 1, 1, tzinfo=UTC),
            local_receipt_time=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert sm.provider_name == "synthetic-fixture"

    def test_naive_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceMetadata(
                provider_name="x",
                provider_mode="fixture",
                source_observation_time=datetime(2026, 1, 1),
                local_receipt_time=datetime(2026, 1, 1),
            )

    def test_blank_provider_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceMetadata(
                provider_name="",
                provider_mode="fixture",
                source_observation_time=datetime(2026, 1, 1, tzinfo=UTC),
                local_receipt_time=datetime(2026, 1, 1, tzinfo=UTC),
            )


class TestContractModel:
    def test_is_frozen(self) -> None:
        class M(ContractModel):
            x: int

        m = M(x=1)
        with pytest.raises(ValidationError):
            m.x = 2  # type: ignore[misc]

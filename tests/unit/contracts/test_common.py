"""Tests for common contract types."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from flight_agent_evaluator.contracts.common import (
    IATAAirlineCode,
    IATAAirportCode,
    ICAOAirportCode,
    ISOCurrencyCode,
    NonEmptyIdentifier,
    NonNegativeDuration,
    NonNegativeInt,
    PositiveInt,
    ProviderName,
    ToolName,
    UtcDateTime,
)


class _Holder(BaseModel):
    """Holder for validating annotated types."""

    iata: IATAAirportCode
    icao: ICAOAirportCode
    airline: IATAAirlineCode
    currency: ISOCurrencyCode
    ident: NonEmptyIdentifier
    pos: PositiveInt
    nnint: NonNegativeInt
    dur: NonNegativeDuration
    provider: ProviderName
    tool: ToolName


class TestIATAAirportCode:
    def test_valid(self) -> None:
        m = _Holder(
            iata="JFK",
            icao="KJFK",
            airline="AA",
            currency="USD",
            ident="x",
            pos=1,
            nnint=0,
            dur=1.0,
            provider="p",
            tool="t",
        )
        assert m.iata == "JFK"

    @pytest.mark.parametrize("value", ["", "jfk", "JK", "JKFF", "12X", "JFK1"])
    def test_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata=value,
                icao="KJFK",
                airline="AA",
                currency="USD",
                ident="x",
                pos=1,
                nnint=0,
                dur=1.0,
                provider="p",
                tool="t",
            )


class TestICAOAirportCode:
    @pytest.mark.parametrize("value", ["", "K", "KJFKX", "kjfk", "KJFK1"])
    def test_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao=value,
                airline="AA",
                currency="USD",
                ident="x",
                pos=1,
                nnint=0,
                dur=1.0,
                provider="p",
                tool="t",
            )

    def test_valid(self) -> None:
        m = _Holder(
            iata="JFK",
            icao="KJFK",
            airline="AA",
            currency="USD",
            ident="x",
            pos=1,
            nnint=0,
            dur=1.0,
            provider="p",
            tool="t",
        )
        assert m.icao == "KJFK"


class TestIATAAirlineCode:
    @pytest.mark.parametrize("value", ["", "A", "AAA", "aa"])
    def test_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao="KJFK",
                airline=value,
                currency="USD",
                ident="x",
                pos=1,
                nnint=0,
                dur=1.0,
                provider="p",
                tool="t",
            )


class TestISOCurrencyCode:
    @pytest.mark.parametrize("value", ["", "US", "USDD", "usd"])
    def test_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao="KJFK",
                airline="AA",
                currency=value,
                ident="x",
                pos=1,
                nnint=0,
                dur=1.0,
                provider="p",
                tool="t",
            )


class TestNonEmptyIdentifier:
    @pytest.mark.parametrize("value", [""])
    def test_rejects_empty(self, value: str) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao="KJFK",
                airline="AA",
                currency="USD",
                ident=value,
                pos=1,
                nnint=0,
                dur=1.0,
                provider="p",
                tool="t",
            )


class TestNumeric:
    @pytest.mark.parametrize("value", [0, -1])
    def test_positive_int_rejects_non_positive(self, value: int) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao="KJFK",
                airline="AA",
                currency="USD",
                ident="x",
                pos=value,
                nnint=0,
                dur=1.0,
                provider="p",
                tool="t",
            )

    @pytest.mark.parametrize("value", [-1])
    def test_non_negative_int_rejects_negative(self, value: int) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao="KJFK",
                airline="AA",
                currency="USD",
                ident="x",
                pos=1,
                nnint=value,
                dur=1.0,
                provider="p",
                tool="t",
            )

    def test_non_negative_int_accepts_zero(self) -> None:
        m = _Holder(
            iata="JFK",
            icao="KJFK",
            airline="AA",
            currency="USD",
            ident="x",
            pos=1,
            nnint=0,
            dur=1.0,
            provider="p",
            tool="t",
        )
        assert m.nnint == 0

    @pytest.mark.parametrize("value", [-1.0, -0.1])
    def test_non_negative_duration_rejects_negative(self, value: float) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao="KJFK",
                airline="AA",
                currency="USD",
                ident="x",
                pos=1,
                nnint=0,
                dur=value,
                provider="p",
                tool="t",
            )


class TestProviderName:
    @pytest.mark.parametrize("value", ["", "Has Spaces", "with.dot"])
    def test_invalid(self, value: str) -> None:
        with pytest.raises(ValidationError):
            _Holder(
                iata="JFK",
                icao="KJFK",
                airline="AA",
                currency="USD",
                ident="x",
                pos=1,
                nnint=0,
                dur=1.0,
                provider=value,
                tool="t",
            )


class TestUtcDateTime:
    def test_now_returns_aware(self) -> None:
        now = UtcDateTime.now()
        assert now.tzinfo is not None
        assert now.utcoffset() is not None
        assert now.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_require_rejects_naive(self) -> None:
        with pytest.raises(ValueError):
            UtcDateTime.require(datetime(2026, 1, 1, 12, 0))

    def test_require_accepts_aware(self) -> None:
        d = UtcDateTime.require(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
        assert d.tzinfo is not None

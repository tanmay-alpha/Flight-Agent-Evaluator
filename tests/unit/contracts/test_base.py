"""Tests for contract base types."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import Field, ValidationError

from flight_agent_evaluator.contracts.base import (
    ContractModel,
    Money,
    NormalisationWarning,
    RawPayloadReference,
    SchemaVersion,
    SourceMetadata,
    json_serialisable_validator,
)

# ---------------------------------------------------------------------------
# ContractModel base behaviour
# ---------------------------------------------------------------------------


class TestContractModel:
    def test_extra_fields_forbidden(self) -> None:
        class Concrete(ContractModel):
            x: int

        with pytest.raises(ValidationError):
            Concrete(x=1, y=2)

    def test_frozen_immutable(self) -> None:
        class Concrete(ContractModel):
            x: int

        c = Concrete(x=1)
        with pytest.raises(Exception):
            c.x = 2  # type: ignore[misc]

    def test_validate_defaults_on_construction(self) -> None:
        # validate_default=True means default values are subject to field validators.
        # Without validate_default, a field with a default of 0 that has ge=0
        # might skip validation; with validate_default=True, it is checked.
        class Concrete(ContractModel):
            x: int = Field(default=0, ge=0)

        # The default of 0 should be accepted and validated.
        c = Concrete()
        assert c.x == 0


# ---------------------------------------------------------------------------
# SchemaVersion
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_defaults(self) -> None:
        s = SchemaVersion(major=1, minor=0, patch=0)
        assert s.major == 1
        assert s.minor == 0
        assert s.patch == 0

    def test_non_negative(self) -> None:
        with pytest.raises(Exception):
            SchemaVersion(major=-1, minor=0, patch=0)  # type: ignore[call-arg]

    def test_from_string_valid(self) -> None:
        s = SchemaVersion.from_string("2.3.4")
        assert s == SchemaVersion(major=2, minor=3, patch=4)

    def test_from_string_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="must be 'major.minor.patch'"):
            SchemaVersion.from_string("not-a-version")

    def test_from_string_too_many_parts(self) -> None:
        with pytest.raises(ValueError):
            SchemaVersion.from_string("1.2.3.4")

    def test_str(self) -> None:
        assert str(SchemaVersion(major=1, minor=2, patch=3)) == "1.2.3"

    def test_equality(self) -> None:
        a = SchemaVersion(major=1, minor=0, patch=0)
        b = SchemaVersion(major=1, minor=0, patch=0)
        assert a == b


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


class TestMoney:
    def test_basic_construction(self) -> None:
        m = Money(amount=Decimal("100.50"), currency="USD")
        assert m.amount == Decimal("100.50")
        assert m.currency == "USD"

    def test_amount_coerced_from_str(self) -> None:
        m = Money(amount="25.00", currency="EUR")
        assert m.amount == Decimal("25.00")

    def test_amount_coerced_from_int(self) -> None:
        m = Money(amount=50, currency="GBP")
        assert m.amount == Decimal("50")

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(Exception):
            Money(amount=Decimal("-1"), currency="USD")  # type: ignore[call-arg]

    def test_invalid_amount_raises(self) -> None:
        with pytest.raises(Exception):
            Money(amount="not-a-number", currency="USD")  # type: ignore[call-arg]

    def test_currency_upper_cased(self) -> None:
        # Lower case rejected by the pattern (upper-casing happens via validator,
        # but the field-pattern constraint fires first in Pydantic v2).
        with pytest.raises(ValidationError, match="pattern"):
            Money(amount=Decimal("1"), currency="usd")

    def test_amount_serializer(self) -> None:
        m = Money(amount=Decimal("100.50"), currency="USD")
        import json

        dumped = m.model_dump_json()
        assert "100.50" in dumped
        # Serializer must produce a string, not a Decimal.
        parsed = json.loads(dumped)
        assert isinstance(parsed["amount"], str)
        assert parsed["amount"] == "100.50"


# ---------------------------------------------------------------------------
# RawPayloadReference
# ---------------------------------------------------------------------------


class TestRawPayloadReference:
    def test_basic(self) -> None:
        ref = RawPayloadReference(
            uri="s3://bucket/key",
            sha256="a" * 64,
        )
        assert ref.sha256 == "a" * 64

    def test_invalid_sha256_rejected(self) -> None:
        with pytest.raises(Exception):
            RawPayloadReference(uri="x", sha256="not-hex")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# NormalisationWarning
# ---------------------------------------------------------------------------


class TestNormalisationWarning:
    def test_basic(self) -> None:
        w = NormalisationWarning(
            field="airport_code",
            original_value="lax",
            normalised_value="LAX",
            reason="Upper-cased airport code",
        )
        assert w.field == "airport_code"
        assert w.original_value == "lax"
        assert w.normalised_value == "LAX"
        assert w.reason == "Upper-cased airport code"


# ---------------------------------------------------------------------------
# SourceMetadata
# ---------------------------------------------------------------------------


class TestSourceMetadata:
    def _source(self) -> SourceMetadata:
        return SourceMetadata(
            provider_name="test-provider",
            provider_mode="live",
            source_observation_time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            local_receipt_time=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
            source_timezone="America/New_York",
            raw_payload_reference=RawPayloadReference(
                uri="s3://bucket/key",
                sha256="b" * 64,
            ),
            normalisation_warnings=(),
        )

    def test_basic_construction(self) -> None:
        source = self._source()
        assert source.provider_name == "test-provider"
        assert source.provider_mode == "live"
        assert source.source_timezone == "America/New_York"

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(Exception):
            SourceMetadata(
                provider_name="x",
                provider_mode="live",
                source_observation_time=datetime(2026, 1, 1, 12, 0, 0),  # naive
                local_receipt_time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            )

    def test_raw_payload_reference_none_default(self) -> None:
        source = SourceMetadata(
            provider_name="x",
            provider_mode="fixture",
            source_observation_time=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            local_receipt_time=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        assert source.raw_payload_reference is None

    def test_normalisation_warnings_default_empty(self) -> None:
        source = SourceMetadata(
            provider_name="x",
            provider_mode="fixture",
            source_observation_time=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            local_receipt_time=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        assert source.normalisation_warnings == ()


# ---------------------------------------------------------------------------
# json_serialisable_validator
# ---------------------------------------------------------------------------


class TestJsonSerialisableValidator:
    def test_none(self) -> None:
        assert json_serialisable_validator(None) is None

    def test_int(self) -> None:
        assert json_serialisable_validator(1) == 1

    def test_float(self) -> None:
        assert json_serialisable_validator(1.5) == 1.5

    def test_bool(self) -> None:
        assert json_serialisable_validator(True) is True

    def test_str(self) -> None:
        assert json_serialisable_validator("x") == "x"

    def test_decimal(self) -> None:
        assert json_serialisable_validator(Decimal("1.5")) == Decimal("1.5")

    def test_list_ok(self) -> None:
        assert json_serialisable_validator([1, "a"]) == [1, "a"]

    def test_list_non_json_item_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-JSON-serialisable"):
            json_serialisable_validator([datetime.utcnow()])

    def test_dict_ok(self) -> None:
        assert json_serialisable_validator({"a": 1}) == {"a": 1}

    def test_dict_non_string_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-string dict key"):
            json_serialisable_validator({1: "x"})

    def test_dict_nested_ok(self) -> None:
        d = {"outer": {"inner": [1, 2]}}
        assert json_serialisable_validator(d) == d

    def test_unsupported_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-JSON-serialisable"):
            json_serialisable_validator(object())

    def test_custom_field_name_in_message(self) -> None:
        with pytest.raises(ValueError, match="'my_field'"):
            json_serialisable_validator(object(), field_name="my_field")

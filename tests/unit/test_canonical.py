"""Tests for canonical JSON utility (ADR 0004)."""

from __future__ import annotations

import hashlib

import pytest

from flight_agent_evaluator.canonical import canonical_hash, canonical_json


class TestCanonicalJsonPrimitives:
    def test_none(self) -> None:
        assert canonical_json(None) == "null"

    def test_bool_true(self) -> None:
        assert canonical_json(True) == "true"

    def test_bool_false(self) -> None:
        assert canonical_json(False) == "false"

    def test_int(self) -> None:
        assert canonical_json(42) == "42"

    def test_negative_int(self) -> None:
        assert canonical_json(-7) == "-7"

    def test_zero(self) -> None:
        assert canonical_json(0) == "0"

    def test_float(self) -> None:
        assert canonical_json(3.14) == "3.14"

    def test_float_zero(self) -> None:
        assert canonical_json(0.0) == "0.0"

    def test_string(self) -> None:
        assert canonical_json("hello") == '"hello"'

    def test_empty_string(self) -> None:
        assert canonical_json("") == '""'


class TestCanonicalJsonStrings:
    def test_string_escape_backslash(self) -> None:
        assert canonical_json("a\\b") == '"a\\\\b"'

    def test_string_escape_quote(self) -> None:
        assert canonical_json('a"b') == '"a\\"b"'

    def test_string_escape_backspace(self) -> None:
        assert canonical_json("a\bb") == '"a\\bb"'

    def test_string_escape_formfeed(self) -> None:
        assert canonical_json("a\fb") == '"a\\fb"'

    def test_string_escape_newline(self) -> None:
        assert canonical_json("a\nb") == '"a\\nb"'

    def test_string_escape_carriage_return(self) -> None:
        assert canonical_json("a\rb") == '"a\\rb"'

    def test_string_escape_tab(self) -> None:
        assert canonical_json("a\tb") == '"a\\tb"'


class TestCanonicalJsonCollections:
    def test_empty_list(self) -> None:
        assert canonical_json([]) == "[]"

    def test_list_of_ints(self) -> None:
        assert canonical_json([1, 2, 3]) == "[1,2,3]"

    def test_list_of_strings(self) -> None:
        assert canonical_json(["a", "b"]) == '["a","b"]'

    def test_nested_list(self) -> None:
        assert canonical_json([[1], [2]]) == "[[1],[2]]"

    def test_empty_dict(self) -> None:
        assert canonical_json({}) == "{}"

    def test_dict_keys_sorted(self) -> None:
        # Insertion order does not matter.
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert canonical_json(a) == canonical_json(b)
        assert canonical_json(a) == '{"a":1,"b":2}'

    def test_dict_separators(self) -> None:
        # Separators are "," and ":" with no whitespace.
        assert canonical_json({"a": 1, "b": 2}) == '{"a":1,"b":2}'

    def test_dict_of_list(self) -> None:
        assert canonical_json({"k": [1, 2]}) == '{"k":[1,2]}'


class TestCanonicalJsonDatetime:
    def test_datetime_utc(self) -> None:
        from datetime import UTC, datetime

        dt = datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC)
        assert canonical_json(dt) == '"2026-01-15T12:30:45+00:00"'

    def test_datetime_with_offset_normalised_to_utc(self) -> None:
        from datetime import datetime, timedelta, timezone

        tz = timezone(timedelta(hours=5))
        dt = datetime(2026, 1, 15, 17, 30, 45, tzinfo=tz)
        # 17:30 in +05:00 == 12:30 UTC
        assert canonical_json(dt) == '"2026-01-15T12:30:45+00:00"'

    def test_naive_datetime_rejected(self) -> None:
        from datetime import datetime

        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="Naive datetime"):
            canonical_json(naive)


class TestCanonicalJsonUuid:
    def test_uuid(self) -> None:
        from uuid import UUID

        u = UUID("12345678-1234-5678-1234-567812345678")
        assert canonical_json(u) == '"12345678-1234-5678-1234-567812345678"'

    def test_uuid_lowercase(self) -> None:
        from uuid import UUID

        u = UUID("ABCDEF12-3456-7890-ABCD-EF1234567890")
        assert canonical_json(u) == '"abcdef12-3456-7890-abcd-ef1234567890"'


class TestCanonicalJsonDecimal:
    def test_decimal_basic(self) -> None:
        from decimal import Decimal

        assert canonical_json(Decimal("123.45")) == "123.45"

    def test_decimal_zero(self) -> None:
        from decimal import Decimal

        assert canonical_json(Decimal("0")) == "0"

    def test_decimal_negative(self) -> None:
        from decimal import Decimal

        assert canonical_json(Decimal("-1.5")) == "-1.5"

    def test_decimal_no_exponent(self) -> None:
        from decimal import Decimal

        # No 'e' in output even for very small numbers.
        assert "e" not in canonical_json(Decimal("0.00001"))


class TestCanonicalJsonFloatExponent:
    def test_float_with_exponent_written_without_e(self) -> None:
        # repr(1e-5) -> '1e-05' must be rendered as '0.00001'.
        assert canonical_json(1e-5) == "0.00001"

    def test_float_normal(self) -> None:
        assert canonical_json(2.5) == "2.5"


class TestCanonicalJsonNonFinite:
    def test_nan_rejected(self) -> None:
        with pytest.raises(ValueError, match="Non-finite"):
            canonical_json(float("nan"))

    def test_positive_infinity_rejected(self) -> None:
        with pytest.raises(ValueError, match="Non-finite"):
            canonical_json(float("inf"))

    def test_negative_infinity_rejected(self) -> None:
        with pytest.raises(ValueError, match="Non-finite"):
            canonical_json(float("-inf"))


class TestCanonicalJsonNonStringKeys:
    def test_int_dict_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="Dict keys must be str"):
            canonical_json({1: "x"})  # type: ignore[dict-item]

    def test_none_dict_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="Dict keys must be str"):
            canonical_json({None: "x"})  # type: ignore[dict-item]


class TestCanonicalJsonUnsupported:
    def test_unsupported_type_rejected(self) -> None:
        class Custom:
            pass

        with pytest.raises(ValueError, match="Unsupported type"):
            canonical_json(Custom())

    def test_set_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported type"):
            canonical_json({1, 2, 3})  # type: ignore[arg-type]


class TestCanonicalHash:
    def test_same_value_same_hash(self) -> None:
        assert canonical_hash({"a": 1}) == canonical_hash({"a": 1})

    def test_different_value_different_hash(self) -> None:
        assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})

    def test_key_order_irrelevant(self) -> None:
        h1 = canonical_hash({"a": 1, "b": 2})
        h2 = canonical_hash({"b": 2, "a": 1})
        assert h1 == h2

    def test_hash_is_sha256_hex(self) -> None:
        h = canonical_hash({"k": "v"})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_matches_direct_sha256(self) -> None:
        payload = {"k": "v"}
        expected = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        assert canonical_hash(payload) == expected


class TestCanonicalDeterminism:
    def test_repeated_calls_stable(self) -> None:
        v = {"b": [2, 1], "a": {"y": 2, "x": 1}}
        first = canonical_json(v)
        for _ in range(10):
            assert canonical_json(v) == first

    def test_complex_payload(self) -> None:
        from datetime import UTC, datetime
        from decimal import Decimal
        from uuid import UUID

        v = {
            "ts": datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
            "amount": Decimal("100.50"),
            "id": UUID("00000000-0000-0000-0000-000000000001"),
            "tags": ["alpha", "beta"],
            "nested": {"count": 2, "ok": True},
        }
        result = canonical_json(v)
        # Decimal rendered without quotes, UUID rendered with quotes.
        assert '"amount":100.50' in result
        assert '"id":"00000000-0000-0000-0000-000000000001"' in result
        assert '"tags":["alpha","beta"]' in result
        assert '"nested":{"count":2,"ok":true}' in result
        assert '"ts":"2026-01-01T00:00:00+00:00"' in result
        # Keys are sorted alphabetically.
        keys_in_order = [
            "amount",
            "id",
            "nested",
            "tags",
            "ts",
        ]
        positions = [result.index(f'"{k}":') for k in keys_in_order]
        assert positions == sorted(positions)


class TestCanonicalSchemaVersion:
    def test_explicit_schema_version(self) -> None:
        # Different versions can produce different output (same value though
        # for version 1 — purely here to ensure the parameter is wired).
        assert canonical_json({}, schema_version=1) == "{}"

    def test_default_version_is_one(self) -> None:
        assert canonical_json({"k": "v"}, schema_version=1) == canonical_json({"k": "v"})

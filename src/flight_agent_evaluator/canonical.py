"""Canonical JSON utility for deterministic hashing.

This module provides a narrowly scoped canonical JSON representation used for
deterministic approval payload hashes and other explicitly hashed contract data.

Policy (ADR 0004):
- UTF-8 encoding.
- Keys sorted.
- Stable separators ("," and ":" — no whitespace).
- No NaN / Infinity (raises ValueError).
- datetime → ISO 8601 with explicit UTC offset (+00:00).
- UUID → canonical 8-4-4-4-12 lowercase hex.
- Decimal → string without exponent (f-string "f" format).
- Other JSON-compatible types pass through unchanged.
- Non-JSON-compatible types raise ValueError.

Policy is versioned so historical hashes remain stable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# Policy version bumps invalidate all historical hashes.
_CANONICAL_VERSION = 1


def canonical_json(value: Any, *, schema_version: int = _CANONICAL_VERSION) -> str:
    """Return a deterministic JSON string for *value*.

    The output is independent of dict insertion order, Decimal repr, and
    datetime formatting.
    """
    return _Encoder(schema_version=schema_version).encode(value)


def canonical_hash(value: Any, *, schema_version: int = _CANONICAL_VERSION) -> str:
    """SHA-256 hex digest of the canonical JSON for *value*."""
    return hashlib.sha256(
        canonical_json(value, schema_version=schema_version).encode("utf-8")
    ).hexdigest()


class _Encoder:
    def __init__(self, *, schema_version: int) -> None:
        self._version = schema_version

    def encode(self, value: Any) -> str:
        return self._convert(value)

    def _convert(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"Non-finite float not allowed in canonical JSON: {value!r}")
            return _format_float(value)
        if isinstance(value, Decimal):
            # No exponent, no sign-prefix artefact.
            return format(value, "f")
        if isinstance(value, str):
            return _json_string(value)
        if isinstance(value, UUID):
            return _json_string(str(value))
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"Naive datetime not allowed in canonical JSON: {value!r}")
            utc_value = value.astimezone(UTC)
            return _json_string(utc_value.strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        if isinstance(value, list):
            elements = ",".join(self._convert(item) for item in value)
            return f"[{elements}]"
        if isinstance(value, dict):
            pairs = []
            for key in sorted(value.keys()):
                if not isinstance(key, str):
                    raise ValueError(f"Dict keys must be str, got {type(key).__name__}: {key!r}")
                pairs.append(f"{_json_string(key)}:{self._convert(value[key])}")
            return "{" + ",".join(pairs) + "}"
        raise ValueError(f"Unsupported type for canonical JSON: {type(value).__name__}")


def _format_float(value: float) -> str:
    # Use repr to avoid any locale-dependent or Python-version formatting issues,
    # then strip any exponent if present.
    s = repr(value)
    if "e" in s.lower():
        # e.g. "1.0e-05" → "0.00001". For canonical JSON we avoid exponents.
        d = Decimal(s)
        return format(d, "f")
    return s


def _json_string(value: str) -> str:
    return (
        '"'
        + value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\f", "\\f")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        + '"'
    )

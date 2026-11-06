"""One strict JSON parser for every untrusted or integrity-relevant input.

``json.loads`` silently keeps the *last* value of a duplicated key, accepts the
non-standard ``NaN``/``Infinity`` literals, and has no size or nesting bound. Each
of those lets two readers (a human reviewer and this tool, or two loaders) see
different content in the same bytes, or lets a NaN slip past numeric ``minimum``
checks. Every loader in the package goes through :func:`loads_strict` or
:func:`load_strict_path` instead.

Rejected: duplicate object keys, NaN / +-Infinity, a UTF-8 BOM, invalid UTF-8,
payloads above ``max_bytes``, and nesting deeper than ``max_depth``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Final

DEFAULT_MAX_BYTES: Final[int] = 5 * 1024 * 1024
DEFAULT_MAX_DEPTH: Final[int] = 64
_BOM: Final[bytes] = b"\xef\xbb\xbf"


class StrictJSONError(ValueError):
    """Raised when input is not strict, bounded JSON."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictJSONError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise StrictJSONError(f"non-finite number {name} is not valid JSON")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        # e.g. 1e999 overflows to inf without passing through parse_constant.
        raise StrictJSONError(f"number {text} overflows to a non-finite value")
    return value


def _check_depth(value: Any, max_depth: int) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children: Any = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        if depth > max_depth:
            raise StrictJSONError(f"nesting deeper than {max_depth} levels")
        stack.extend((child, depth + 1) for child in children)


def loads_strict(
    data: bytes | str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    source: str = "input",
) -> Any:
    """Decode ``data`` as strict, bounded JSON; raise :class:`StrictJSONError` otherwise."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > max_bytes:
        raise StrictJSONError(f"{source}: {len(raw)} bytes exceeds the {max_bytes}-byte limit")
    if raw.startswith(_BOM):
        raise StrictJSONError(f"{source}: UTF-8 BOM is not allowed")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StrictJSONError(f"{source}: invalid UTF-8 ({exc.reason})") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except StrictJSONError as exc:
        raise StrictJSONError(f"{source}: {exc}") from None
    except RecursionError:
        raise StrictJSONError(f"{source}: nesting deeper than {max_depth} levels") from None
    except json.JSONDecodeError as exc:
        raise StrictJSONError(
            f"{source}: invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from None
    try:
        _check_depth(value, max_depth)
    except StrictJSONError as exc:
        raise StrictJSONError(f"{source}: {exc}") from None
    return value


def load_strict_path(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Any:
    """Read ``path`` without loading more than ``max_bytes + 1`` bytes, then parse strictly."""
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    return loads_strict(raw, max_bytes=max_bytes, max_depth=max_depth, source=path.name)


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DEPTH",
    "StrictJSONError",
    "load_strict_path",
    "loads_strict",
]

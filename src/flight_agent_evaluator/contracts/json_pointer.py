"""Strict RFC 6901 JSON Pointer utility.

Distinguishes missing fields from JSON null (None) values, enforces bounds,
and handles RFC 6901 escaping (~0 -> ~, ~1 -> /).
"""

from typing import Any, Final


class _MissingSentinel:
    """Sentinel type representing a missing key or index in a JSON document."""

    def __repr__(self) -> str:
        return "<MISSING>"


MISSING: Final[_MissingSentinel] = _MissingSentinel()
MAX_POINTER_DEPTH: Final[int] = 32


def resolve_json_pointer(doc: Any, pointer: str, max_depth: int = MAX_POINTER_DEPTH) -> Any:
    """Resolve RFC 6901 JSON *pointer* against *doc*.

    Returns ``MISSING`` if the key or index does not exist in *doc*.
    Raises ``ValueError`` if *pointer* is malformed, has invalid escape sequences,
    negative array indexes, or exceeds *max_depth*.
    """
    if not isinstance(pointer, str):
        raise ValueError(f"JSON pointer must be a string, got {type(pointer).__name__}")

    if pointer == "":
        return doc

    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/' or be empty, got '{pointer}'")

    tokens = pointer[1:].split("/")
    if len(tokens) > max_depth:
        raise ValueError(
            f"JSON pointer depth ({len(tokens)}) exceeds maximum allowed ({max_depth})"
        )

    current: Any = doc
    for raw_token in tokens:
        # Validate escape sequences according to RFC 6901.
        # ~ must be followed by 0 or 1.
        idx = 0
        token_chars: list[str] = []
        while idx < len(raw_token):
            ch = raw_token[idx]
            if ch == "~":
                if idx + 1 >= len(raw_token):
                    raise ValueError(
                        f"Malformed JSON pointer escape sequence in '{raw_token}': unescaped '~' at end"
                    )
                next_ch = raw_token[idx + 1]
                if next_ch == "0":
                    token_chars.append("~")
                    idx += 2
                elif next_ch == "1":
                    token_chars.append("/")
                    idx += 2
                else:
                    raise ValueError(
                        f"Malformed JSON pointer escape sequence '~{next_ch}' in '{raw_token}'"
                    )
            else:
                token_chars.append(ch)
                idx += 1

        token = "".join(token_chars)

        if isinstance(current, dict):
            if token not in current:
                return MISSING
            current = current[token]
        elif isinstance(current, (list, tuple)):
            # Index must be a non-negative integer without leading zeros unless it is "0".
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise ValueError(f"Invalid array index '{token}' in JSON pointer for list/tuple")
            arr_idx = int(token)
            if arr_idx < 0:
                raise ValueError(f"Negative array index '{token}' not allowed in JSON pointer")
            if arr_idx >= len(current):
                return MISSING
            current = current[arr_idx]
        else:
            return MISSING

    return current

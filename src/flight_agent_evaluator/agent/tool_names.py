"""Reversible mapping between internal tool names and provider function names.

Internal evaluator tool names are dotted (``flight.get_status``), while
OpenAI-compatible function names must match ``^[a-zA-Z0-9_-]{1,64}$``.  The
mapping is applied only at the provider wire boundary; journals, manifests and
evaluator evidence always carry the internal names.
"""

from __future__ import annotations

import re

PROVIDER_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_NAMESPACE_SEPARATOR = "."
_PROVIDER_SEPARATOR = "__"


class ToolNameEncodingError(ValueError):
    """Raised when an internal tool name cannot be mapped reversibly."""


def to_provider_tool_name(internal_name: str) -> str:
    """Encode an internal dotted tool name as a provider-safe function name."""
    encoded = internal_name.replace(_NAMESPACE_SEPARATOR, _PROVIDER_SEPARATOR)
    if (
        not PROVIDER_TOOL_NAME_PATTERN.fullmatch(encoded)
        or from_provider_tool_name(encoded) != internal_name
    ):
        raise ToolNameEncodingError(
            f"Internal tool name {internal_name!r} does not map reversibly to a "
            f"provider-safe function name (got {encoded!r})."
        )
    return encoded


def from_provider_tool_name(provider_name: str) -> str:
    """Decode a provider function name back into the internal dotted tool name."""
    return provider_name.replace(_PROVIDER_SEPARATOR, _NAMESPACE_SEPARATOR)


__all__ = [
    "PROVIDER_TOOL_NAME_PATTERN",
    "ToolNameEncodingError",
    "from_provider_tool_name",
    "to_provider_tool_name",
]

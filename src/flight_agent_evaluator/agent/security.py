"""Security and secret redaction for model agent logs and journal entries."""

from __future__ import annotations

import re
from typing import Any

# Standard pattern for redacting API keys, Bearer tokens, and secrets
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_]{20,}", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE),
    re.compile(r"api[_\-]?key[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9._\-]{16,})[\"']?", re.IGNORECASE),
]

_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "secret",
    "access_token",
    "token",
    "auth_token",
    "password",
}


def redact_secrets(data: Any, custom_secrets: list[str] | None = None) -> Any:
    """Recursively redact secrets and credentials from data structures.

    Replaces matching secret tokens and values of sensitive dict keys with
    ``"[REDACTED_SECRET]"``. Does not mutate input objects.
    """
    if custom_secrets:
        patterns = list(_SECRET_PATTERNS) + [
            re.compile(re.escape(s), re.IGNORECASE) for s in custom_secrets if s
        ]
    else:
        patterns = _SECRET_PATTERNS

    def _redact_str(val: str) -> str:
        res = val
        for pat in patterns:
            res = pat.sub("[REDACTED_SECRET]", res)
        return res

    if isinstance(data, str):
        return _redact_str(data)

    if isinstance(data, dict):
        new_dict: dict[str, Any] = {}
        for k, v in data.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                new_dict[k] = "[REDACTED_SECRET]"
            else:
                new_dict[k] = redact_secrets(v, custom_secrets=custom_secrets)
        return new_dict

    if isinstance(data, list):
        return [redact_secrets(item, custom_secrets=custom_secrets) for item in data]

    if isinstance(data, tuple):
        return tuple(redact_secrets(item, custom_secrets=custom_secrets) for item in data)

    return data

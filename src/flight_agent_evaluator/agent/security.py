"""Security utilities, secret redaction, and benchmark reference leakage scanning."""

from __future__ import annotations

import json
import re
from typing import Any

from flight_agent_evaluator.contracts.model import ModelRequest

_SENSITIVE_KEYS = {"api_key", "authorization", "token", "secret", "password", "access_token"}
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\._\-]+", re.IGNORECASE)
_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9]{15,}")


def redact_secrets(
    data: Any,
    custom_secrets: list[str] | None = None,
) -> Any:
    """Recursively redact secrets, bearer tokens, API keys, and custom strings from structures."""
    secrets = set(custom_secrets or [])
    secrets = {s for s in secrets if s and s != "mock-key" and len(s) > 3}

    if isinstance(data, str):
        redacted = data
        for secret in secrets:
            redacted = redacted.replace(secret, "[REDACTED_SECRET]")
        redacted = _SK_PATTERN.sub("[REDACTED_SECRET]", redacted)
        redacted = _BEARER_PATTERN.sub("[REDACTED_SECRET]", redacted)
        return redacted

    if isinstance(data, dict):
        result = {}
        for k, v in data.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                result[k] = "[REDACTED_SECRET]"
            else:
                result[k] = redact_secrets(v, custom_secrets=custom_secrets)
        return result

    if isinstance(data, list):
        return [redact_secrets(item, custom_secrets=custom_secrets) for item in data]
    if isinstance(data, tuple):
        return tuple(redact_secrets(item, custom_secrets=custom_secrets) for item in data)

    return data


def scan_request_for_reference_leakage(
    request: ModelRequest,
    forbidden_markers: list[str],
) -> list[str]:
    """Scan a ModelRequest for presence of forbidden reference answer markers."""
    violations: list[str] = []
    request_str = json.dumps(request.model_dump(), default=str)

    for marker in forbidden_markers:
        if not marker or len(marker.strip()) < 3:
            continue
        if marker in request_str:
            violations.append(
                f"Reference answer leakage detected in turn {request.turn_index}: marker '{marker[:15]}...' present"
            )

    return violations

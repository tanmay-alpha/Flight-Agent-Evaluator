"""Idempotency key registry for state-mutating operations.

Ensures that retry attempts with the same idempotency key return the cached
result without executing the side-effect twice.

Raises IdempotencyConflictError if the same idempotency key is reused
with a different request payload.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.environment.contracts import IdempotencyRecord
from flight_agent_evaluator.environment.errors import IdempotencyConflictError


class IdempotencyKeyRegistry:
    """In-memory idempotency key registry."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], IdempotencyRecord] = {}

    def get_record(self, key: str, tool_name: str | None = None) -> IdempotencyRecord | None:
        """Return the record for an idempotency key, or None if not registered."""
        if tool_name is not None:
            return self._records.get((tool_name, key))
        matches = [record for (tool, raw_key), record in self._records.items() if raw_key == key]
        return matches[0] if len(matches) == 1 else None

    def check_or_register(
        self,
        *,
        key: str,
        tool_name: str,
        payload: dict[str, Any],
        registered_at: datetime,  # noqa: ARG002
    ) -> IdempotencyRecord | None:
        """Check an idempotency key.

        If key is NEW: returns None (caller should execute operation, then call save_result).
        If key is REUSED with SAME payload: returns existing IdempotencyRecord.
        If key is REUSED with DIFFERENT payload: raises IdempotencyConflictError.
        """
        existing = self._records.get((tool_name, key))
        if existing is None:
            return None

        current_hash = canonical_hash(payload)
        if existing.payload_hash != current_hash:
            raise IdempotencyConflictError(
                f"Idempotency key '{key}' was previously used with payload hash "
                f"'{existing.payload_hash[:8]}...' but current payload hash is '{current_hash[:8]}...'."
            )

        return existing.model_copy(update={"result_payload": deepcopy(existing.result_payload)})

    def save_result(
        self,
        *,
        key: str,
        tool_name: str,
        payload: dict[str, Any],
        result_payload: dict[str, Any],
        registered_at: datetime,
    ) -> IdempotencyRecord:
        """Save a new idempotency record after successful operation execution."""
        p_hash = canonical_hash(payload)
        existing = self._records.get((tool_name, key))
        if existing is not None:
            if existing.payload_hash != p_hash:
                raise IdempotencyConflictError(
                    f"Idempotency key '{key}' is already bound to a different {tool_name!r} request."
                )
            return existing.model_copy(update={"result_payload": deepcopy(existing.result_payload)})
        record = IdempotencyRecord(
            key=key,
            payload_hash=p_hash,
            tool_name=tool_name,
            result_payload=deepcopy(result_payload),
            registered_at=registered_at,
        )
        self._records[(tool_name, key)] = record
        return record.model_copy(update={"result_payload": deepcopy(record.result_payload)})

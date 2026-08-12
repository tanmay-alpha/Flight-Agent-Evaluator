"""Idempotency key registry for state-mutating operations.

Ensures that retry attempts with the same idempotency key return the cached
result without executing the side-effect twice.

Raises IdempotencyConflictError if the same idempotency key is reused
with a different request payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.environment.contracts import IdempotencyRecord
from flight_agent_evaluator.environment.errors import IdempotencyConflictError


class IdempotencyKeyRegistry:
    """In-memory idempotency key registry."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def get_record(self, key: str) -> IdempotencyRecord | None:
        """Return the record for an idempotency key, or None if not registered."""
        return self._records.get(key)

    def check_or_register(
        self,
        *,
        key: str,
        tool_name: str,  # noqa: ARG002
        payload: dict[str, Any],
        registered_at: datetime,  # noqa: ARG002
    ) -> IdempotencyRecord | None:
        """Check an idempotency key.

        If key is NEW: returns None (caller should execute operation, then call save_result).
        If key is REUSED with SAME payload: returns existing IdempotencyRecord.
        If key is REUSED with DIFFERENT payload: raises IdempotencyConflictError.
        """
        existing = self._records.get(key)
        if existing is None:
            return None

        current_hash = canonical_hash(payload)
        if existing.payload_hash != current_hash:
            raise IdempotencyConflictError(
                f"Idempotency key '{key}' was previously used with payload hash "
                f"'{existing.payload_hash[:8]}...' but current payload hash is '{current_hash[:8]}...'."
            )

        return existing

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
        record = IdempotencyRecord(
            key=key,
            payload_hash=p_hash,
            tool_name=tool_name,
            result_payload=result_payload,
            registered_at=registered_at,
        )
        self._records[key] = record
        return record

"""Deterministic identifier factory for the runtime engine.

Phase 2 IDs are UUIDv5 derived from:

- scenario ID;
- scenario version;
- seed;
- record type;
- monotonic sequence number.

Same inputs always produce identical UUIDs across runs, processes, and
Python versions. The runtime engine never produces UUIDv4 identifiers.
"""

from __future__ import annotations

import uuid


class DeterministicIdFactory:
    """Build deterministic UUIDv5 identifiers for runtime events."""

    _NAMESPACE = uuid.NAMESPACE_DNS

    def __init__(
        self,
        scenario_id: str,
        scenario_version: int,
        seed: int,
    ) -> None:
        self._prefix = f"{scenario_id}|v{scenario_version}|s{seed}"

    def next(self, record_type: str, sequence: int) -> uuid.UUID:
        """Return a UUIDv5 derived from the fixed inputs.

        Parameters
        ----------
        record_type:
            A stable category name (e.g. ``"tool_call"``, ``"tool_result"``).
        sequence:
            A monotonic sequence number unique within this run.

        Returns
        -------
        uuid.UUID
            UUIDv5 derived deterministically from all inputs.
        """
        name = f"{self._prefix}|{record_type}|{sequence}"
        return uuid.uuid5(self._NAMESPACE, name)
"""Deterministic virtual clock for the runtime engine.

Phase 2 requires a clock that:

- starts from a fixed scenario reference time;
- advances only through explicit operations;
- never reads the system wall clock;
- returns timezone-aware UTC datetimes;
- rejects negative advances;
- isolates per-run state.

No real system-clock implementation is required in Phase 2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class VirtualClock(Protocol):
    """Protocol for a clock the runtime engine reads."""

    def now(self) -> datetime:
        """Return the current logical time."""

    def advance(self, seconds: int) -> datetime:
        """Advance the logical clock by *seconds* and return the new time."""


class DeterministicVirtualClock:
    """A clock that advances only through explicit ``advance()`` calls.

    Designed for deterministic evaluation runs across Windows and Linux.
    Per-run isolation: each instance has its own state; no shared mutable
    state. The wall clock is never read.
    """

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError(
                f"Clock start must be timezone-aware, got {start!r}"
            )
        self._current: datetime = start.astimezone(UTC)

    def now(self) -> datetime:
        """Return the current logical time (UTC, timezone-aware)."""
        return self._current

    def advance(self, seconds: int) -> datetime:
        """Advance the clock by *seconds* and return the new time.

        Raises ``ValueError`` if seconds is negative.
        """
        if seconds < 0:
            raise ValueError(
                f"Clock cannot advance by negative seconds: {seconds}"
            )
        self._current = self._current + timedelta(seconds=seconds)
        return self._current

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


class VirtualClock:
    """Base class for a clock the runtime engine reads.

    ``VirtualClock`` is an abstract base; ``DeterministicVirtualClock`` is
    the canonical implementation. Tests may instantiate ``VirtualClock``
    directly when they want a clock that defaults to the Unix epoch and
    returns a deterministic, UTC-anchored time.
    """

    def __init__(self, start: datetime | None = None) -> None:
        if start is None:
            # Default to a fixed reference time (epoch 1, UTC) so that
            # instantiating VirtualClock() without arguments still gives
            # a deterministic, timezone-aware clock.
            start = datetime(2026, 1, 1, tzinfo=UTC)
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError(f"Clock start must be timezone-aware, got {start!r}")
        self._current: datetime = start.astimezone(UTC)

    def now(self) -> datetime:
        """Return the current logical time (UTC, timezone-aware)."""
        return self._current

    def advance(self, seconds: int) -> datetime:
        """Advance the clock by *seconds* and return the new time.

        Raises ``ValueError`` if seconds is negative.
        """
        if seconds < 0:
            raise ValueError(f"Clock cannot advance by negative seconds: {seconds}")
        self._current = self._current + timedelta(seconds=seconds)
        return self._current


class DeterministicVirtualClock(VirtualClock):
    """A clock that advances only through explicit ``advance()`` calls.

    Designed for deterministic evaluation runs across Windows and Linux.
    Per-run isolation: each instance has its own state; no shared mutable
    state. The wall clock is never read.
    """

    def __init__(self, start: datetime) -> None:
        super().__init__(start=start)

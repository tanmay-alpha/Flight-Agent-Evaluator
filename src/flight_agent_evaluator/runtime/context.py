"""Immutable per-run context for the runtime engine.

Phase 2 RunContext contains the run identity, scenario identity, seed,
clock, ID factory, limits, and digests. It must NEVER contain credentials,
filesystem paths, or provider secrets.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from flight_agent_evaluator.runtime.clock import VirtualClock
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory


@dataclass(frozen=True)
class RunContext:
    """Immutable context for a single evaluation run.

    Mutation is blocked at the dataclass level. All fields are stable
    for the duration of the run.
    """

    run_id: uuid.UUID
    scenario_id: str
    scenario_version: int
    seed: int
    clock: VirtualClock
    id_factory: DeterministicIdFactory
    tool_call_limit: int
    time_limit_seconds: int
    correlation_id: str
    scenario_digest: str
    trajectory_digest: str

    def __post_init__(self) -> None:
        # Convert ``run_id`` (which may be a string from JSON or a UUID)
        # to a real UUID object. Frozen dataclasses do not allow __setattr__,
        # so we use object.__setattr__.
        import uuid as _uuid

        if not isinstance(self.run_id, _uuid.UUID):
            object.__setattr__(
                self,
                "run_id",
                _uuid.UUID(str(self.run_id)),
            )

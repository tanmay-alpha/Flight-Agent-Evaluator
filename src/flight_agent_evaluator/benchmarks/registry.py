"""Authoritative benchmark agent registry with exact identity resolution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flight_agent_evaluator.agent.baselines import (
    NaiveBaselineAgent,
    RandomBaselineAgent,
    ScriptedOracleAgent,
)
from flight_agent_evaluator.agent.protocol import AgentPolicy
from flight_agent_evaluator.benchmarks.loader import BenchmarkIntegrityError


class UnknownBenchmarkAgentError(BenchmarkIntegrityError):
    """Raised when an agent identifier does not match any registered benchmark policy."""


class BenchmarkAgentRegistry:
    """Registry managing exact, authenticated benchmark agent identities."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], AgentPolicy]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(
            agent_id="scripted-oracle",
            factory=ScriptedOracleAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
            description="Executes golden reference trajectory steps.",
        )
        self.register(
            agent_id="oracle",
            factory=ScriptedOracleAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
            description="Executes golden reference trajectory steps.",
        )
        self.register(
            agent_id="scripted",
            factory=ScriptedOracleAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
            description="Executes golden reference trajectory steps.",
        )
        self.register(
            agent_id="baseline-scripted",
            factory=ScriptedOracleAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
            description="Executes golden reference trajectory steps.",
        )
        self.register(
            agent_id="naive-baseline",
            factory=NaiveBaselineAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.NaiveBaselineAgent",
            description="Fixed status lookup and simple alternative search heuristic.",
        )
        self.register(
            agent_id="naive",
            factory=NaiveBaselineAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.NaiveBaselineAgent",
            description="Fixed status lookup and simple alternative search heuristic.",
        )
        self.register(
            agent_id="baseline-naive",
            factory=NaiveBaselineAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.NaiveBaselineAgent",
            description="Fixed status lookup and simple alternative search heuristic.",
        )
        self.register(
            agent_id="random-baseline",
            factory=RandomBaselineAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.RandomBaselineAgent",
            description="Executes random valid tool actions across available schemas.",
        )
        self.register(
            agent_id="random",
            factory=RandomBaselineAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.RandomBaselineAgent",
            description="Executes random valid tool actions across available schemas.",
        )
        self.register(
            agent_id="baseline-random",
            factory=RandomBaselineAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.RandomBaselineAgent",
            description="Executes random valid tool actions across available schemas.",
        )

    def register(
        self,
        agent_id: str,
        factory: Callable[[], AgentPolicy],
        agent_version: str = "1.0.0",
        implementation: str = "",
        description: str = "",
    ) -> None:
        """Register an exact agent policy factory."""
        aid = agent_id.strip()
        if not aid:
            raise ValueError("agent_id cannot be empty.")
        self._factories[aid] = factory
        self._metadata[aid] = {
            "agent_id": aid,
            "agent_version": agent_version,
            "implementation": implementation or getattr(factory, "__name__", str(factory)),
            "description": description,
        }

    def resolve(self, agent_id: str) -> AgentPolicy:
        """Resolve an exact agent policy instance. Fails closed on any unknown identifier."""
        aid = agent_id.strip()
        if aid not in self._factories:
            known = sorted(self._factories.keys())
            raise UnknownBenchmarkAgentError(
                f"Unknown or unregistered benchmark agent ID '{agent_id}'. "
                f"Registered agents: {known}."
            )
        return self._factories[aid]()

    def get_metadata(self, agent_id: str) -> dict[str, Any]:
        """Retrieve registered metadata for an agent ID."""
        aid = agent_id.strip()
        if aid not in self._metadata:
            raise UnknownBenchmarkAgentError(f"Unknown agent ID '{agent_id}'.")
        return dict(self._metadata[aid])

    def list_agents(self) -> list[dict[str, Any]]:
        """List all registered agent identities and their metadata."""
        return [dict(meta) for meta in self._metadata.values()]

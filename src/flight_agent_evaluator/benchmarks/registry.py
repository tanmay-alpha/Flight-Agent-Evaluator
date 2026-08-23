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
    """Registry managing exact registered benchmark agent identities."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], AgentPolicy]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._aliases: dict[str, str] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        # Canonical benchmark agent identities
        self.register(
            agent_id="scripted-oracle",
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
            agent_id="random-baseline",
            factory=RandomBaselineAgent,
            agent_version="1.0.0",
            implementation="flight_agent_evaluator.agent.baselines.RandomBaselineAgent",
            description="Executes random valid tool actions across available schemas.",
        )

        # Explicit aliases pointing to canonical identities
        self.register_alias("oracle", "scripted-oracle")
        self.register_alias("scripted", "scripted-oracle")
        self.register_alias("baseline-scripted", "scripted-oracle")
        self.register_alias("naive", "naive-baseline")
        self.register_alias("baseline-naive", "naive-baseline")
        self.register_alias("random", "random-baseline")
        self.register_alias("baseline-random", "random-baseline")

    def register(
        self,
        agent_id: str,
        factory: Callable[[], AgentPolicy],
        agent_version: str = "1.0.0",
        implementation: str = "",
        description: str = "",
    ) -> None:
        """Register an exact canonical agent policy factory."""
        aid = agent_id.strip()
        if not aid:
            raise ValueError("agent_id cannot be empty.")
        self._factories[aid] = factory
        self._metadata[aid] = {
            "agent_id": aid,
            "agent_version": agent_version,
            "implementation": implementation or getattr(factory, "__name__", str(factory)),
            "description": description,
            "is_alias": False,
        }

    def register_alias(self, alias_id: str, canonical_id: str) -> None:
        """Register a recognized compatibility alias for a canonical agent identity."""
        a = alias_id.strip()
        c = canonical_id.strip()
        if not a or not c:
            raise ValueError("Alias and canonical ID cannot be empty.")
        if c not in self._factories:
            raise UnknownBenchmarkAgentError(f"Cannot alias to unknown agent ID '{canonical_id}'.")
        self._aliases[a] = c

    def resolve(self, agent_id: str) -> AgentPolicy:
        """Resolve an exact agent policy instance. Fails closed on any unknown identifier."""
        aid = agent_id.strip()
        if aid in self._factories:
            return self._factories[aid]()
        if aid in self._aliases:
            canonical_id = self._aliases[aid]
            return self._factories[canonical_id]()
        known = sorted(list(self._factories.keys()) + list(self._aliases.keys()))
        raise UnknownBenchmarkAgentError(
            f"Unknown or unregistered benchmark agent ID '{agent_id}'. Registered agents: {known}."
        )

    def get_metadata(self, agent_id: str) -> dict[str, Any]:
        """Retrieve registered metadata for an agent ID."""
        aid = agent_id.strip()
        if aid in self._metadata:
            return dict(self._metadata[aid])
        if aid in self._aliases:
            canonical_id = self._aliases[aid]
            meta = dict(self._metadata[canonical_id])
            meta["alias_of"] = canonical_id
            return meta
        raise UnknownBenchmarkAgentError(f"Unknown agent ID '{agent_id}'.")

    def list_agents(self, include_aliases: bool = False) -> list[dict[str, Any]]:
        """List registered canonical agent identities (and optionally aliases)."""
        if not include_aliases:
            return [dict(meta) for meta in self._metadata.values() if not meta.get("is_alias")]
        items = [dict(meta) for meta in self._metadata.values()]
        for alias_id, canonical_id in self._aliases.items():
            items.append(
                {
                    "agent_id": alias_id,
                    "canonical_id": canonical_id,
                    "is_alias": True,
                    "description": f"Compatibility alias for '{canonical_id}'.",
                }
            )
        return items

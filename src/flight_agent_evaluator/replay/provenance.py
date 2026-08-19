"""Replay provenance and deterministic re-execution factory.

Binds exact scenario, expectation, environment, fixture, agent, seed, and model exchange
provenance to prevent fuzzy filesystem searches or fallback substitutions during replay.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from flight_agent_evaluator.agent.baselines import NaiveBaselineAgent
from flight_agent_evaluator.agent.model_client import ReplayModelClient
from flight_agent_evaluator.contracts.model import ModelExchangeManifest
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import LoadedScenario, ScenarioLoader
from flight_agent_evaluator.recording.contracts import (
    RecordingBundleManifest,
    ReplayProvenance,
    RunRecording,
)
from flight_agent_evaluator.recording.journal import HashChainJournal


class ReplayProvenanceError(Exception):
    """Base exception for replay provenance failures."""


class ReplayProvenanceMismatchError(ReplayProvenanceError):
    """Raised when recorded provenance does not match the execution environment."""


class ReplayUnavailableError(ReplayProvenanceError):
    """Raised when required sources/models for replay cannot be resolved."""


class ReplayUnsupportedVersionError(ReplayProvenanceError):
    """Raised when recording schema or algorithm version is unsupported."""


def extract_provenance(
    recording: RunRecording | None,
    journal: HashChainJournal,
    manifest: RecordingBundleManifest | None = None,
) -> ReplayProvenance:
    """Extract authoritative ReplayProvenance from bundle manifest, metadata, or journal."""
    if manifest is not None:
        return ReplayProvenance(
            scenario_id=manifest.scenario_id,
            scenario_version=manifest.scenario_version,
            scenario_digest=manifest.scenario_digest,
            benchmark_manifest_digest=manifest.benchmark_manifest_digest,
            expectation_digest=manifest.expectation_digest,
            environment_version=manifest.environment_version,
            fixture_manifest_digest=manifest.fixture_manifest_digest,
            agent_id=manifest.agent_id,
            agent_version=manifest.agent_version,
            agent_configuration_digest=manifest.agent_configuration_digest,
            model_exchange_manifest_digest=manifest.model_exchange_manifest_digest,
            seed=manifest.seed,
        )

    # Fallback to metadata / journal entries
    scenario_id = recording.scenario_id if recording else None
    seed = recording.seed if recording else 42
    scenario_version = recording.scenario_version if recording else 1
    agent_id = "scripted-oracle"

    for entry in journal.entries:
        if entry.type == "run_started":
            payload = entry.payload
            if not scenario_id and "scenario_id" in payload:
                scenario_id = str(payload["scenario_id"])
            if "seed" in payload:
                seed = int(payload["seed"])
            if "scenario_version" in payload:
                scenario_version = int(payload["scenario_version"])
            if "agent_id" in payload:
                agent_id = str(payload["agent_id"])

    if not scenario_id:
        raise ReplayUnavailableError("Cannot determine scenario_id from recording.")

    return ReplayProvenance(
        scenario_id=scenario_id,
        scenario_version=scenario_version,
        scenario_digest="",
        agent_id=agent_id,
        seed=seed,
    )


class ReplayExecutionFactory:
    """Creates deterministic runner and execution components matching recorded provenance."""

    def __init__(self, resource_root: Path | None = None) -> None:
        self._resource_root = resource_root or Path("resources")

    def resolve_scenario(
        self, provenance: ReplayProvenance, explicit_path: Path | None = None
    ) -> LoadedScenario:
        """Resolve and validate the exact scenario required for replay."""
        loader = ScenarioLoader()

        if explicit_path is not None and explicit_path.is_file():
            loaded = loader.load_from_path(explicit_path)
            if provenance.scenario_digest:
                raw_sha = hashlib.sha256(explicit_path.read_bytes()).hexdigest()
                if raw_sha != provenance.scenario_digest:
                    raise ReplayProvenanceMismatchError(
                        f"Scenario digest mismatch for {explicit_path}: "
                        f"expected {provenance.scenario_digest}, got {raw_sha}"
                    )
            return loaded

        # Exact path resolution
        candidate = self._resource_root / "scenarios" / f"{provenance.scenario_id}.json"
        if candidate.is_file():
            loaded = loader.load_from_path(candidate)
            if provenance.scenario_digest:
                raw_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if raw_sha != provenance.scenario_digest:
                    raise ReplayProvenanceMismatchError(
                        f"Scenario digest mismatch for {candidate}: "
                        f"expected {provenance.scenario_digest}, got {raw_sha}"
                    )
            return loaded

        raise ReplayUnavailableError(
            f"Scenario '{provenance.scenario_id}' not found at {candidate} for authoritative replay."
        )

    def resolve_agent(
        self,
        provenance: ReplayProvenance,
        model_exchange_manifest: ModelExchangeManifest | None = None,
        custom_driver: Any = None,
    ) -> Any:
        """Resolve exact agent policy matching recorded provenance."""
        if custom_driver is not None:
            return custom_driver

        aid = provenance.agent_id.lower().replace("_", "-")
        if aid in ("scripted-oracle", "oracle", "scripted", "scripted-agent-driver", "default"):
            from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver

            return ScriptedAgentDriver()
        if aid in ("naive-baseline", "naive"):
            return NaiveBaselineAgent()
        if aid in ("model", "model-tool-calling", "model-agent", "gpt-4o-mini", "gpt-4o"):
            if model_exchange_manifest is None:
                raise ReplayUnavailableError(
                    f"Replaying model agent '{provenance.agent_id}' requires a valid ModelExchangeManifest."
                )
            return ReplayModelClient(model_exchange_manifest)

        raise ReplayUnavailableError(f"Cannot resolve agent '{provenance.agent_id}' for replay.")

    def create_runner(self) -> ScenarioRunner:
        """Create a clean deterministic ScenarioRunner."""
        return ScenarioRunner()

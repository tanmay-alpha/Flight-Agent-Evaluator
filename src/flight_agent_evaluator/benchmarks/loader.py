"""Secure resource loader and content-addressing verifier for benchmark manifests."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from flight_agent_evaluator.benchmarks.manifest import BenchmarkManifest, BenchmarkScenarioEntry
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.trajectory_expectation import (
    TrajectoryExpectation,
    validate_trajectory_expectation,
)

logger = logging.getLogger(__name__)


class BenchmarkIntegrityError(Exception):
    """Base exception for benchmark integrity and security failures."""


class ManifestValidationError(BenchmarkIntegrityError):
    """Raised when manifest schema or cross-entity consistency check fails."""


class ResourceDigestMismatchError(BenchmarkIntegrityError):
    """Raised when on-disk file bytes do not match the authoritative manifest digest."""


class PathSecurityError(BenchmarkIntegrityError):
    """Raised when a resource path violates security constraints or root confinement."""


@dataclass(frozen=True)
class BenchmarkCase:
    """Authoritative, cryptographically verified benchmark execution case."""

    manifest_entry: BenchmarkScenarioEntry
    scenario: BenchmarkScenario
    expectation: TrajectoryExpectation
    scenario_raw_sha256: str
    expectation_raw_sha256: str

    def __post_init__(self) -> None:
        if self.scenario.scenario_id.id != self.manifest_entry.scenario_id:
            raise ManifestValidationError(
                f"Scenario ID mismatch: entry has '{self.manifest_entry.scenario_id}' "
                f"but scenario payload has '{self.scenario.scenario_id.id}'."
            )
        if self.expectation.scenario_id != self.manifest_entry.scenario_id:
            raise ManifestValidationError(
                f"Expectation ID mismatch: entry has '{self.manifest_entry.scenario_id}' "
                f"but expectation payload has '{self.expectation.scenario_id}'."
            )


class BenchmarkManifestLoader:
    """Loads and verifies authoritative benchmark manifests and bound resources."""

    def __init__(self, resource_root: Path | str | None = None) -> None:
        if resource_root is not None:
            self.resource_root = Path(resource_root).resolve()
        else:
            self.resource_root = Path(".").resolve()

    def resolve_secure_path(self, rel_path: str) -> Path:
        """Resolve a relative resource path within the confined resource root."""
        norm_path = rel_path.replace("\\", "/").lstrip("/")
        candidate = (self.resource_root / norm_path).resolve()
        try:
            if not candidate.is_relative_to(self.resource_root):
                raise PathSecurityError(
                    f"Path security violation: '{rel_path}' escapes resource root '{self.resource_root}'."
                )
        except AttributeError:
            # Fallback for Python < 3.9 if needed
            try:
                candidate.relative_to(self.resource_root)
            except ValueError as err:
                raise PathSecurityError(
                    f"Path security violation: '{rel_path}' escapes resource root '{self.resource_root}'."
                ) from err

        if not candidate.exists():
            raise PathSecurityError(f"Resource not found: '{rel_path}' (resolved: '{candidate}').")
        if not candidate.is_file():
            raise PathSecurityError(
                f"Resource is not a regular file: '{rel_path}' (resolved: '{candidate}')."
            )
        return candidate

    def verify_file_digest(self, file_path: Path, expected_sha256: str) -> bytes:
        """Read exact raw bytes and verify against expected SHA-256 digest."""
        raw_bytes = file_path.read_bytes()
        actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            raise ResourceDigestMismatchError(
                f"Resource digest mismatch for '{file_path.name}': "
                f"expected '{expected_sha256}', got '{actual_sha256}'."
            )
        return raw_bytes

    def load_manifest(
        self,
        manifest_path: Path | str,
        verify_resources: bool = True,
    ) -> tuple[BenchmarkManifest, list[BenchmarkCase]]:
        """Load, validate, and cryptographically verify a benchmark manifest and all its cases."""
        p = Path(manifest_path)
        if not p.is_file():
            raise BenchmarkIntegrityError(f"Benchmark manifest file not found: '{manifest_path}'.")

        raw_manifest_bytes = p.read_bytes()
        try:
            data = json.loads(raw_manifest_bytes.decode("utf-8"))
            manifest = BenchmarkManifest.model_validate(data)
        except Exception as exc:
            raise ManifestValidationError(f"Invalid benchmark manifest schema: {exc}") from exc

        # Verify manifest canonical digest if specified in manifest
        computed_digest = manifest.compute_canonical_digest()
        if manifest.manifest_digest and manifest.manifest_digest.lower() != computed_digest.lower():
            raise ManifestValidationError(
                f"Manifest canonical digest mismatch: declared '{manifest.manifest_digest}', "
                f"computed '{computed_digest}'."
            )

        cases: list[BenchmarkCase] = []
        if verify_resources:
            for entry in manifest.scenarios:
                # 1. Resolve and verify scenario bytes
                sc_file = self.resolve_secure_path(entry.scenario_path)
                sc_bytes = self.verify_file_digest(sc_file, entry.scenario_sha256)
                try:
                    sc_data = json.loads(sc_bytes.decode("utf-8"))
                    scenario = BenchmarkScenario.model_validate(sc_data)
                except Exception as exc:
                    raise ManifestValidationError(
                        f"Failed to parse validated scenario '{entry.scenario_id}': {exc}"
                    ) from exc

                # 2. Resolve and verify expectation bytes
                exp_file = self.resolve_secure_path(entry.expectation_path)
                exp_bytes = self.verify_file_digest(exp_file, entry.expectation_sha256)
                try:
                    exp_data = json.loads(exp_bytes.decode("utf-8"))
                    expectation = TrajectoryExpectation.model_validate(exp_data)
                except Exception as exc:
                    raise ManifestValidationError(
                        f"Failed to parse validated expectation '{entry.scenario_id}': {exc}"
                    ) from exc

                exp_errors = validate_trajectory_expectation(expectation)
                if exp_errors:
                    raise ManifestValidationError(
                        f"Expectation graph validation failed for '{entry.scenario_id}': {exp_errors}"
                    )

                # 3. Construct verified case
                case = BenchmarkCase(
                    manifest_entry=entry,
                    scenario=scenario,
                    expectation=expectation,
                    scenario_raw_sha256=entry.scenario_sha256,
                    expectation_raw_sha256=entry.expectation_sha256,
                )
                cases.append(case)

        return manifest, cases

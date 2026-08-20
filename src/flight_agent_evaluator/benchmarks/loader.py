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

    def load_builtin(
        self,
        benchmark_id: str = "benchmark-v1",
        verify_resources: bool = True,
    ) -> tuple[BenchmarkManifest, list[BenchmarkCase]]:
        """Load and verify a built-in benchmark manifest bundled in package data."""
        from flight_agent_evaluator.resources.contracts import (
            ResourceKind,
            ResourceOrigin,
            ResourceRef,
        )
        from flight_agent_evaluator.resources.locator import (
            get_builtin_locator,
            sanitize_logical_path,
        )

        logical = benchmark_id.strip()
        if not logical.endswith(".json") and "/" not in logical and "\\" not in logical:
            logical = f"benchmarks/{logical}.json"
        elif not logical.startswith("benchmarks/"):
            logical = f"benchmarks/{logical}"

        sanitized = sanitize_logical_path(logical)
        ref = ResourceRef(
            origin=ResourceOrigin.BUILTIN,
            logical_path=sanitized,
            kind=ResourceKind.BENCHMARK_MANIFEST,
        )
        locator = get_builtin_locator()
        raw_manifest_bytes = locator.read_bytes(ref)

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
                sc_log = entry.scenario_path.replace("\\", "/").lstrip("/")
                if sc_log.startswith("resources/"):
                    sc_log = sc_log[len("resources/") :]
                sc_ref = ResourceRef(
                    origin=ResourceOrigin.BUILTIN,
                    logical_path=sanitize_logical_path(sc_log),
                    kind=ResourceKind.SCENARIO,
                    expected_sha256=entry.scenario_sha256,
                )
                sc_bytes = locator.read_bytes(sc_ref)
                try:
                    sc_data = json.loads(sc_bytes.decode("utf-8"))
                    scenario = BenchmarkScenario.model_validate(sc_data)
                except Exception as exc:
                    raise ManifestValidationError(
                        f"Failed to parse validated scenario '{entry.scenario_id}': {exc}"
                    ) from exc

                # 2. Resolve and verify expectation bytes
                exp_log = entry.expectation_path.replace("\\", "/").lstrip("/")
                if exp_log.startswith("resources/"):
                    exp_log = exp_log[len("resources/") :]
                exp_ref = ResourceRef(
                    origin=ResourceOrigin.BUILTIN,
                    logical_path=sanitize_logical_path(exp_log),
                    kind=ResourceKind.EXPECTATION,
                    expected_sha256=entry.expectation_sha256,
                )
                exp_bytes = locator.read_bytes(exp_ref)
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

    def load_manifest(
        self,
        manifest_path: Path | str,
        verify_resources: bool = True,
    ) -> tuple[BenchmarkManifest, list[BenchmarkCase]]:
        """Load, validate, and cryptographically verify a benchmark manifest and all its cases.

        Supports 'builtin:<id>' URIs or filesystem paths.
        """
        path_str = str(manifest_path).strip()
        if path_str.startswith("builtin:"):
            bid = path_str[len("builtin:") :].strip()
            return self.load_builtin(bid, verify_resources=verify_resources)

        p = Path(path_str)
        if not p.is_file():
            # Check if user specified a simple name like "benchmark-v1" that might be a builtin
            if (
                not p.exists()
                and not path_str.endswith(".json")
                and "/" not in path_str
                and "\\" not in path_str
            ):
                try:
                    return self.load_builtin(path_str, verify_resources=verify_resources)
                except Exception:  # noqa: S110
                    pass
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

        manifest_root = p.parent.resolve()
        cases: list[BenchmarkCase] = []
        if verify_resources:
            for entry in manifest.scenarios:
                # 1. Resolve and verify scenario bytes
                sc_path_cand = Path(entry.scenario_path)
                if sc_path_cand.is_absolute():
                    sc_file = sc_path_cand
                elif (manifest_root / sc_path_cand).is_file():
                    sc_file = (manifest_root / sc_path_cand).resolve()
                elif (self.resource_root / sc_path_cand).is_file():
                    sc_file = (self.resource_root / sc_path_cand).resolve()
                else:
                    # Strip leading resources/ if relative to manifest parent
                    clean_rel = entry.scenario_path.replace("\\", "/").lstrip("/")
                    if (
                        clean_rel.startswith("resources/")
                        and (manifest_root / clean_rel[len("resources/") :]).is_file()
                    ):
                        sc_file = (manifest_root / clean_rel[len("resources/") :]).resolve()
                    else:
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
                exp_path_cand = Path(entry.expectation_path)
                if exp_path_cand.is_absolute():
                    exp_file = exp_path_cand
                elif (manifest_root / exp_path_cand).is_file():
                    exp_file = (manifest_root / exp_path_cand).resolve()
                elif (self.resource_root / exp_path_cand).is_file():
                    exp_file = (self.resource_root / exp_path_cand).resolve()
                else:
                    clean_exp_rel = entry.expectation_path.replace("\\", "/").lstrip("/")
                    if (
                        clean_exp_rel.startswith("resources/")
                        and (manifest_root / clean_exp_rel[len("resources/") :]).is_file()
                    ):
                        exp_file = (manifest_root / clean_exp_rel[len("resources/") :]).resolve()
                    else:
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

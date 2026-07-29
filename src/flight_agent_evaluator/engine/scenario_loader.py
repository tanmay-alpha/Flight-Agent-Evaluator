"""Strict scenario loader for the Phase 2 runtime.

Scenarios are machine-readable JSON files. The loader:

- Rejects bytes beyond a configurable size limit.
- Rejects BOM-prefixed files.
- Rejects unknown top-level keys (``extra="forbid"`` via Pydantic).
- Rejects unsupported scenario schema major versions.
- Validates the scenario against ``BenchmarkScenario``.
- Computes a SHA-256 digest of the raw bytes for provenance.
- Optionally enforces an ``allowed_root`` for path safety.
- Rejects symlinks.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario

_DEFAULT_MAX_BYTES: Final[int] = 1_048_576  # 1 MiB
_BOM = b"\xef\xbb\xbf"
_MAX_SUPPORTED_SCHEMA_MAJOR: Final[int] = 1


class ScenarioLoaderError(Exception):
    """Raised when scenario loading fails for a non-validation reason."""


class ScenarioVersionMismatchError(Exception):
    """Raised when the scenario schema version is not supported."""


class LoadedScenario:
    """The result of loading and validating a scenario."""

    def __init__(self, scenario: BenchmarkScenario, digest: str, raw_bytes: bytes) -> None:
        self.scenario = scenario
        self.digest = digest
        self.raw_bytes = raw_bytes


class ScenarioLoader:
    """Load, validate, and digest benchmark scenarios from local JSON files."""

    def __init__(self, max_bytes: int = _DEFAULT_MAX_BYTES, *, allowed_root: Path | None = None) -> None:
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {max_bytes}")
        self._max_bytes = max_bytes
        self._allowed_root = allowed_root

    def load_from_path(self, path: Path) -> LoadedScenario:
        """Load and validate a scenario from a local JSON file.

        Parameters
        ----------
        path:
            Path to the JSON scenario file.

        Returns
        -------
        LoadedScenario
            The validated scenario, its SHA-256 digest, and the raw bytes.

        Raises
        ------
        ScenarioLoaderError
            If the file is missing, too large, contains a BOM, is not valid
            JSON, or is outside the allowed root.
        ScenarioVersionMismatchError
            If the scenario schema version is not supported.
        """
        # Reject symlinks.
        if path.is_symlink():
            raise ScenarioLoaderError(
                f"Scenario file must not be a symlink: {path}"
            )

        # Path safety check.
        self._check_path_safety(path)

        # BOM check
        raw = path.read_bytes()
        if raw.startswith(_BOM):
            raise ScenarioLoaderError("Scenario file has a BOM prefix")

        # Size check
        if len(raw) > self._max_bytes:
            raise ScenarioLoaderError(
                f"Scenario file exceeds maximum size of {self._max_bytes} bytes "
                f"({len(raw)} bytes)"
            )

        # Parse JSON (reject NaN/Infinity via standard parser; rejects duplicate keys
        # only if json.loads is called with object_pairs_hook, but we rely on
        # Pydantic extra=forbid to reject duplicates once we get the dict).
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScenarioLoaderError(f"Invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ScenarioLoaderError("Scenario file must be a JSON object")

        # Schema version gate
        sv = data.get("schema_version")
        if isinstance(sv, str):
            parts = sv.split(".")
            if parts and int(parts[0]) > _MAX_SUPPORTED_SCHEMA_MAJOR:
                raise ScenarioVersionMismatchError(
                    f"Unsupported scenario schema version: {sv!r} "
                    f"(max supported major: {_MAX_SUPPORTED_SCHEMA_MAJOR})"
                )

        # Validate against BenchmarkSchema
        try:
            scenario = BenchmarkScenario.model_validate(data)
        except ValidationError as exc:
            raise ScenarioLoaderError(
                f"Scenario validation failed: {exc}"
            ) from exc

        # Digest
        digest = hashlib.sha256(raw).hexdigest()

        return LoadedScenario(
            scenario=scenario,
            digest=digest,
            raw_bytes=raw,
        )

    def _check_path_safety(self, path: Path) -> None:
        """Raise if the path is outside the allowed root or unsafe."""
        if not path.exists():
            raise ScenarioLoaderError(f"Scenario file not found: {path}")

        if self._allowed_root is None:
            return

        try:
            resolved_path = path.resolve(strict=True)
            resolved_root = self._allowed_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ScenarioLoaderError(f"Failed to resolve path: {exc}") from exc

        try:
            resolved_path.relative_to(resolved_root)
        except ValueError as exc:
            raise ScenarioLoaderError(
                f"Scenario file is outside the allowed root: {path}"
            ) from exc
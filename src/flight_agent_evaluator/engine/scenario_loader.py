"""Strict scenario loader for the Phase 2 runtime.

Scenarios are machine-readable JSON files. The loader:

- Rejects bytes beyond a configurable size limit.
- Rejects BOM-prefixed files.
- Rejects duplicate top-level keys deterministically.
- Rejects NaN/Infinity values.
- Rejects unknown top-level keys (``extra="forbid"`` via Pydantic).
- Rejects unsupported scenario schema major versions.
- Validates the scenario against ``BenchmarkScenario``.
- Computes a SHA-256 digest of the raw bytes for provenance.
- Enforces path containment only when an explicit ``allowed_root`` is configured.
- Rejects symlinks and files larger than the size limit before reading them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.strict_json import StrictJSONError, loads_strict

_DEFAULT_MAX_BYTES: Final[int] = 1_048_576  # 1 MiB
_BOM = b"\xef\xbb\xbf"
_MAX_SUPPORTED_SCHEMA_MAJOR: Final[int] = 1


class ScenarioLoaderError(Exception):
    """Raised when scenario loading fails for a non-validation reason."""


class ScenarioVersionMismatchError(Exception):
    """Raised when the scenario schema version is not supported."""


class LoadedScenario:
    """The result of loading and validating a scenario."""

    __slots__ = ("scenario", "digest", "raw_bytes")

    def __init__(self, scenario: BenchmarkScenario, digest: str, raw_bytes: bytes) -> None:
        self.scenario = scenario
        self.digest = digest
        self.raw_bytes = raw_bytes


class ScenarioLoader:
    """Load, validate, and digest benchmark scenarios from local JSON files.

    The constructor accepts an optional ``allowed_root`` for path-safety
    enforcement. If provided, scenario files must resolve below that
    directory tree. If omitted, no containment check is performed: callers
    loading untrusted paths must pass ``allowed_root``.
    """

    def __init__(
        self,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        allowed_root: Path | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {max_bytes}")
        self._max_bytes = max_bytes
        self._allowed_root = allowed_root

    def load_from_bytes(self, raw: bytes, expected_sha256: str | None = None) -> LoadedScenario:
        """Parse, validate, and digest a BenchmarkScenario from raw bytes."""
        if raw.startswith(_BOM):
            raise ScenarioLoaderError("Scenario file has a BOM prefix")
        if len(raw) > self._max_bytes:
            raise ScenarioLoaderError(
                f"Scenario file is too large: {len(raw)} bytes "
                f"exceeds maximum of {self._max_bytes} bytes"
            )

        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 and digest.lower() != expected_sha256.lower():
            raise ScenarioLoaderError(
                f"Scenario raw SHA-256 digest mismatch: expected '{expected_sha256}', got '{digest}'."
            )

        try:
            data = loads_strict(raw, max_bytes=self._max_bytes, source="scenario")
        except StrictJSONError as exc:
            raise ScenarioLoaderError(str(exc)) from exc

        if not isinstance(data, dict):
            raise ScenarioLoaderError("Scenario file must be a JSON object")

        # Schema version gate — must be supported.
        sv = data.get("schema_version")
        if isinstance(sv, str):
            parts = sv.split(".")
            if parts:
                try:
                    major = int(parts[0])
                except ValueError:
                    raise ScenarioVersionMismatchError(
                        f"Malformed schema version major: {sv!r}"
                    ) from None
                if major > _MAX_SUPPORTED_SCHEMA_MAJOR:
                    raise ScenarioVersionMismatchError(
                        f"Unsupported scenario schema version: {sv!r} "
                        f"(max supported major: {_MAX_SUPPORTED_SCHEMA_MAJOR})"
                    )
        elif sv is not None:
            raise ScenarioVersionMismatchError(
                f"Malformed schema_version type: expected str, got {type(sv).__name__}"
            )

        # Validate against BenchmarkScenario.
        try:
            scenario = BenchmarkScenario.model_validate(data)
        except ValidationError as exc:
            raise ScenarioLoaderError(f"Scenario validation failed: {exc}") from exc

        return LoadedScenario(
            scenario=scenario,
            digest=digest,
            raw_bytes=raw,
        )

    def load_from_text(self, text: str, expected_sha256: str | None = None) -> LoadedScenario:
        """Parse and validate a BenchmarkScenario from a UTF-8 string."""
        return self.load_from_bytes(text.encode("utf-8"), expected_sha256=expected_sha256)

    def load_resource(
        self,
        ref: Any,
        locator: Any | None = None,
    ) -> LoadedScenario:
        """Load a BenchmarkScenario from a ResourceRef and ResourceLocator."""
        from flight_agent_evaluator.resources.contracts import ResourceOrigin
        from flight_agent_evaluator.resources.locator import get_builtin_locator

        if ref.origin == ResourceOrigin.BUILTIN:
            loc = locator or get_builtin_locator()
            raw = loc.read_bytes(ref)
            return self.load_from_bytes(raw, expected_sha256=ref.expected_sha256)

        if locator is not None:
            raw = locator.read_bytes(ref)
            return self.load_from_bytes(raw, expected_sha256=ref.expected_sha256)

        return self.load_from_path(Path(ref.logical_path), expected_sha256=ref.expected_sha256)

    def load_builtin(self, scenario_id_or_path: str) -> LoadedScenario:
        """Load a built-in packaged scenario by scenario ID or logical path.

        A bare id (``approval-denied``) resolves to ``scenarios/<id>.json`` and then to
        ``scenarios/transactional/<id>.json``.
        """
        from flight_agent_evaluator.resources.contracts import (
            BuiltinResourceNotFound,
            ResourceKind,
            ResourceOrigin,
            ResourceRef,
        )
        from flight_agent_evaluator.resources.locator import (
            get_builtin_locator,
            sanitize_logical_path,
        )

        logical = scenario_id_or_path.strip()
        if not logical.endswith(".json") and "/" not in logical and "\\" not in logical:
            candidates = [f"scenarios/{logical}.json", f"scenarios/transactional/{logical}.json"]
        elif not logical.startswith("scenarios/"):
            candidates = [f"scenarios/{logical}"]
        else:
            candidates = [logical]

        def _ref(path: str) -> ResourceRef:
            return ResourceRef(
                origin=ResourceOrigin.BUILTIN,
                logical_path=sanitize_logical_path(path),
                kind=ResourceKind.SCENARIO,
            )

        locator = get_builtin_locator()
        *fallbacks_first, last = candidates
        for candidate in fallbacks_first:
            try:
                return self.load_resource(_ref(candidate), locator)
            except BuiltinResourceNotFound:
                continue
        return self.load_resource(_ref(last), locator)

    def load_from_path(self, path: Path, expected_sha256: str | None = None) -> LoadedScenario:
        """Load a scenario from an explicit filesystem Path."""
        # Reject symlinks unconditionally.
        if path.is_symlink():
            raise ScenarioLoaderError(f"Scenario file must not be a symlink: {path}")

        # Resolve and verify path safety.
        self._check_path_safety(path)

        size = path.stat().st_size
        if size > self._max_bytes:
            raise ScenarioLoaderError(
                f"Scenario file too large ({size} > {self._max_bytes} bytes): {path}"
            )
        raw = path.read_bytes()
        return self.load_from_bytes(raw, expected_sha256=expected_sha256)

    def _check_path_safety(self, path: Path) -> None:
        root = self._allowed_root
        if root is not None:
            # Only enforce path containment when an explicit allowed root is configured.
            try:
                root_resolved = root.resolve(strict=False)
                resolved_path = path.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise ScenarioLoaderError(f"Failed to resolve path: {exc}") from exc
            try:
                resolved_path.relative_to(root_resolved)
            except ValueError as exc:
                raise ScenarioLoaderError(
                    f"Scenario file is outside the allowed root: {path}"
                ) from exc

        if not path.exists():
            raise ScenarioLoaderError(f"Scenario file not found: {path}")


__all__ = [
    "LoadedScenario",
    "ScenarioLoader",
    "ScenarioLoaderError",
    "ScenarioVersionMismatchError",
]

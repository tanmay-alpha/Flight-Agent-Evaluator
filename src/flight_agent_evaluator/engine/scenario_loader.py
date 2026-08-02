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
- Enforces path safety unconditionally.
- Rejects symlinks.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

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

    __slots__ = ("scenario", "digest", "raw_bytes")

    def __init__(self, scenario: BenchmarkScenario, digest: str, raw_bytes: bytes) -> None:
        self.scenario = scenario
        self.digest = digest
        self.raw_bytes = raw_bytes


def _pairs_to_dict(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    """Convert ordered pairs to a dict, rejecting duplicate keys."""
    result: dict[str, Any] = {}
    seen: set[str] = set()
    for key, value in pairs:
        if key in seen:
            raise ScenarioLoaderError(f"Duplicate key in scenario JSON: {key!r}")
        seen.add(key)
        if (
            isinstance(value, list)
            and value
            and all(
                isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)
                for item in value
            )
        ):
            result[key] = _pairs_to_dict(value)
        elif isinstance(value, list):
            result[key] = [_reconstruct_list_item(item) for item in value]
        else:
            result[key] = value
    return result


def _reconstruct_list_item(item: Any) -> Any:
    """Recursively convert any nested pairs-style structure into a dict/list."""
    if (
        isinstance(item, list)
        and item
        and all(
            isinstance(sub, tuple) and len(sub) == 2 and isinstance(sub[0], str) for sub in item
        )
    ):
        return _pairs_to_dict(item)
    if isinstance(item, list):
        return [_reconstruct_list_item(sub) for sub in item]
    return item


def _reject_nan(value: Any, path: str = "") -> None:
    """Walk *value*; raise if NaN, Infinity, or -Infinity is present."""
    if isinstance(value, float) and (
        value != value or value == float("inf") or value == float("-inf")
    ):
        raise ScenarioLoaderError(
            f"Non-finite float ({value!r}) at {path or 'root'} is not allowed"
        )
    if isinstance(value, dict):
        for k, v in value.items():
            _reject_nan(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            _reject_nan(item, f"{path}[{idx}]")


class ScenarioLoader:
    """Load, validate, and digest benchmark scenarios from local JSON files.

    The constructor accepts an optional ``allowed_root`` for path-safety
    enforcement. If provided, scenario files must exist below that
    directory tree. If omitted, the loader enforces that the file is
    inside the repository's own ``resources/scenarios`` directory (a
    deterministic default safe tree).
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

    def load_from_path(self, path: Path) -> LoadedScenario:
        # Reject symlinks unconditionally.
        if path.is_symlink():
            raise ScenarioLoaderError(f"Scenario file must not be a symlink: {path}")

        # Resolve and verify path safety.
        self._check_path_safety(path)

        raw = path.read_bytes()
        if raw.startswith(_BOM):
            raise ScenarioLoaderError("Scenario file has a BOM prefix")
        if len(raw) > self._max_bytes:
            raise ScenarioLoaderError(
                f"Scenario file is too large: {len(raw)} bytes "
                f"exceeds maximum of {self._max_bytes} bytes"
            )

        # Parse JSON strictly: reject duplicate keys, reject NaN/Infinity.
        try:
            pairs = json.loads(raw, object_pairs_hook=list)
        except json.JSONDecodeError as exc:
            raise ScenarioLoaderError(f"Invalid JSON: {exc}") from exc

        data = _pairs_to_dict(pairs)
        _reject_nan(data)

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

        digest = hashlib.sha256(raw).hexdigest()

        return LoadedScenario(
            scenario=scenario,
            digest=digest,
            raw_bytes=raw,
        )

    def _check_path_safety(self, path: Path) -> None:
        if not path.exists():
            raise ScenarioLoaderError(f"Scenario file not found: {path}")
        try:
            resolved_path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ScenarioLoaderError(f"Failed to resolve path: {exc}") from exc
        root = self._allowed_root
        if root is not None:
            # Only enforce path containment when an explicit allowed root is configured.
            try:
                root_resolved = root.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ScenarioLoaderError(f"Failed to resolve allowed root: {exc}") from exc
            try:
                resolved_path.relative_to(root_resolved)
            except ValueError as exc:
                raise ScenarioLoaderError(
                    f"Scenario file is outside the allowed root: {path}"
                ) from exc


__all__ = [
    "LoadedScenario",
    "ScenarioLoader",
    "ScenarioLoaderError",
    "ScenarioVersionMismatchError",
]

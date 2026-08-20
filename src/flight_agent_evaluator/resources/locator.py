"""Authoritative resource locators and URI parsing for built-in and external resources."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.resources
import re
from collections.abc import Generator
from pathlib import Path
from typing import Protocol

from flight_agent_evaluator.resources.contracts import (
    BuiltinResourceNotFound,
    ExternalResourceNotFound,
    PackagedResourceIntegrityError,
    ResourceError,
    ResourceKind,
    ResourceOrigin,
    ResourceRef,
    ResourceSecurityError,
)

# Maximum allowed size for a single loaded resource (32 MiB)
MAX_RESOURCE_BYTES = 32 * 1024 * 1024


def sanitize_logical_path(path_str: str) -> str:
    """Validate and normalize a logical resource path to POSIX style.

    Rejects path traversals ('..'), absolute paths, null bytes, and Windows drive indicators.
    """
    if "\x00" in path_str:
        raise ResourceSecurityError("Null bytes forbidden in resource paths.")

    # Convert Windows backslashes to forward slashes for logical path consistency
    normalized = path_str.replace("\\", "/").strip()

    if not normalized:
        raise ResourceSecurityError("Empty resource path is invalid.")

    # Disallow Windows drive prefixes like C:
    if re.match(r"^[A-Za-z]:", normalized):
        raise ResourceSecurityError(
            f"Drive identifiers forbidden in logical resource paths: {path_str}"
        )

    # Disallow leading slash (must be relative logical path)
    if normalized.startswith("/"):
        raise ResourceSecurityError(
            f"Absolute paths forbidden in logical resource paths: {path_str}"
        )

    # Check components for path traversal
    parts = normalized.split("/")
    for part in parts:
        if part in ("..", ""):
            raise ResourceSecurityError(f"Path traversal or empty segment forbidden: {path_str}")

    return "/".join(parts)


class ResourceLocator(Protocol):
    """Protocol for reading and verifying resource contents."""

    def read_bytes(self, ref: ResourceRef) -> bytes:
        """Read raw bytes for a resource, enforcing size bounds and expected digest."""
        ...

    def read_text(self, ref: ResourceRef, encoding: str = "utf-8") -> str:
        """Read text for a resource."""
        ...

    def exists(self, ref: ResourceRef) -> bool:
        """Check if a resource exists."""
        ...

    def digest(self, ref: ResourceRef) -> str:
        """Compute the SHA-256 digest of a resource."""
        ...

    def iter_children(self, logical_prefix: str, kind: ResourceKind) -> list[ResourceRef]:
        """Iterate child resources under a logical prefix."""
        ...


class BuiltinResourceLocator:
    """Authoritative locator for resources bundled inside the installed package."""

    def __init__(self, package_root: str = "flight_agent_evaluator.resources") -> None:
        self._package_root = package_root

    def _get_traversable(self, logical_path: str) -> importlib.resources.abc.Traversable:
        sanitized = sanitize_logical_path(logical_path)
        parts = sanitized.split("/")
        try:
            node = importlib.resources.files(self._package_root)
            for part in parts:
                node = node.joinpath(part)
            return node
        except Exception as exc:
            raise BuiltinResourceNotFound(
                f"Failed resolving built-in resource {logical_path!r}: {exc}"
            ) from exc

    def exists(self, ref: ResourceRef) -> bool:
        """Check if the built-in resource exists."""
        try:
            node = self._get_traversable(ref.logical_path)
            return node.is_file()
        except Exception:
            return False

    def read_bytes(self, ref: ResourceRef) -> bytes:
        """Read bytes for a built-in resource with integrity and size verification."""
        sanitized = sanitize_logical_path(ref.logical_path)
        node = self._get_traversable(sanitized)
        if not node.is_file():
            raise BuiltinResourceNotFound(f"Built-in resource not found: {sanitized}")

        try:
            data = node.read_bytes()
        except Exception as exc:
            raise BuiltinResourceNotFound(
                f"Failed reading built-in resource {sanitized!r}: {exc}"
            ) from exc

        if len(data) > MAX_RESOURCE_BYTES:
            raise ResourceError(
                f"Resource {sanitized} exceeds maximum allowed size of {MAX_RESOURCE_BYTES} bytes."
            )

        if ref.expected_sha256:
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != ref.expected_sha256:
                raise PackagedResourceIntegrityError(
                    f"Built-in resource {sanitized} SHA-256 digest mismatch: "
                    f"expected {ref.expected_sha256}, got {actual_sha}"
                )

        return data

    def read_text(self, ref: ResourceRef, encoding: str = "utf-8") -> str:
        """Read UTF-8 text for a built-in resource."""
        raw = self.read_bytes(ref)
        try:
            return raw.decode(encoding)
        except Exception as exc:
            raise PackagedResourceIntegrityError(
                f"Built-in resource {ref.logical_path} could not be decoded as {encoding}: {exc}"
            ) from exc

    def digest(self, ref: ResourceRef) -> str:
        """Compute SHA-256 digest of built-in resource bytes."""
        data = self.read_bytes(ref)
        return hashlib.sha256(data).hexdigest()

    def iter_children(self, logical_prefix: str, kind: ResourceKind) -> list[ResourceRef]:
        """Iterate all files under a logical prefix inside package resources."""
        sanitized = sanitize_logical_path(logical_prefix)
        node = self._get_traversable(sanitized)
        if not node.is_dir():
            return []

        results: list[ResourceRef] = []
        for child in sorted(node.iterdir(), key=lambda c: c.name):
            if child.is_file():
                child_logical = f"{sanitized}/{child.name}"
                results.append(
                    ResourceRef(
                        origin=ResourceOrigin.BUILTIN,
                        logical_path=child_logical,
                        kind=kind,
                    )
                )
        return results

    @contextlib.contextmanager
    def materialize(self, ref: ResourceRef) -> Generator[Path, None, None]:
        """Materialize built-in resource as a real Path for legacy components."""
        node = self._get_traversable(ref.logical_path)
        if not node.is_file():
            raise BuiltinResourceNotFound(f"Built-in resource not found: {ref.logical_path}")
        with importlib.resources.as_file(node) as real_path:
            yield Path(real_path)

    def list_builtin_benchmarks(self) -> list[str]:
        """List all available built-in benchmark IDs (e.g. 'benchmark-v1', 'demo-v1')."""
        try:
            node = importlib.resources.files(self._package_root).joinpath("benchmarks")
            if not node.is_dir():
                return []
            return [
                child.name[:-5]
                for child in sorted(node.iterdir(), key=lambda c: c.name)
                if child.is_file() and child.name.endswith(".json")
            ]
        except Exception:
            return []


class ExternalResourceLocator:
    """Locator for user-supplied external files on the local filesystem."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self._root_dir = root_dir.resolve() if root_dir else None

    @property
    def root_dir(self) -> Path | None:
        return self._root_dir

    def _resolve_path(self, logical_path: str) -> Path:
        p = Path(logical_path)
        if p.is_absolute():
            resolved = p.resolve()
        elif self._root_dir is not None:
            resolved = (self._root_dir / p).resolve()
        else:
            resolved = p.resolve()

        return resolved

    def exists(self, ref: ResourceRef) -> bool:
        """Check if the external file exists."""
        try:
            target = self._resolve_path(ref.logical_path)
            return target.is_file()
        except Exception:
            return False

    def read_bytes(self, ref: ResourceRef) -> bytes:
        """Read bytes from external file with integrity and size checks."""
        target = self._resolve_path(ref.logical_path)
        if not target.is_file():
            raise ExternalResourceNotFound(f"External resource file not found: {target}")

        try:
            size = target.stat().st_size
            if size > MAX_RESOURCE_BYTES:
                raise ResourceError(
                    f"External resource {target} exceeds maximum allowed size of {MAX_RESOURCE_BYTES} bytes."
                )
            data = target.read_bytes()
        except Exception as exc:
            if isinstance(exc, ResourceError):
                raise
            raise ExternalResourceNotFound(
                f"Failed reading external resource {target}: {exc}"
            ) from exc

        if ref.expected_sha256:
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != ref.expected_sha256:
                raise PackagedResourceIntegrityError(
                    f"External resource {target} SHA-256 digest mismatch: "
                    f"expected {ref.expected_sha256}, got {actual_sha}"
                )

        return data

    def read_text(self, ref: ResourceRef, encoding: str = "utf-8") -> str:
        """Read text from external file."""
        data = self.read_bytes(ref)
        try:
            return data.decode(encoding)
        except Exception as exc:
            raise ResourceError(
                f"External resource {ref.logical_path} could not be decoded as {encoding}: {exc}"
            ) from exc

    def digest(self, ref: ResourceRef) -> str:
        """Compute SHA-256 digest of external resource."""
        data = self.read_bytes(ref)
        return hashlib.sha256(data).hexdigest()

    def iter_children(self, logical_prefix: str, kind: ResourceKind) -> list[ResourceRef]:
        """Iterate children in external directory."""
        target = self._resolve_path(logical_prefix)
        if not target.is_dir():
            return []

        return [
            ResourceRef(
                origin=ResourceOrigin.EXTERNAL,
                logical_path=str(child),
                kind=kind,
                resolved_path=str(child.resolve()),
            )
            for child in sorted(target.iterdir())
            if child.is_file()
        ]

    @contextlib.contextmanager
    def materialize(self, ref: ResourceRef) -> Generator[Path, None, None]:
        """External resources are already on filesystem."""
        target = self._resolve_path(ref.logical_path)
        if not target.is_file():
            raise ExternalResourceNotFound(f"External resource not found: {target}")
        yield target


_GLOBAL_BUILTIN_LOCATOR: BuiltinResourceLocator | None = None


def get_builtin_locator() -> BuiltinResourceLocator:
    """Return singleton BuiltinResourceLocator instance."""
    global _GLOBAL_BUILTIN_LOCATOR
    if _GLOBAL_BUILTIN_LOCATOR is None:
        _GLOBAL_BUILTIN_LOCATOR = BuiltinResourceLocator()
    return _GLOBAL_BUILTIN_LOCATOR


def parse_resource_uri(
    uri_or_path: str,
    default_kind: ResourceKind | None = None,
) -> ResourceRef:
    """Parse a resource string into an authoritative ResourceRef.

    Supports:
    - 'builtin:<logical_id>' -> Built-in packaged resource (e.g. 'builtin:benchmark-v1', 'builtin:scenarios/jfk-lhr-delay.json')
    - 'file:<path>' -> External filesystem resource
    - '<plain_path>' -> External filesystem resource (including Windows drive 'C:\\...')
    """
    raw = uri_or_path.strip()
    if not raw:
        raise ResourceError("Empty resource URI or path.")

    if raw.startswith("builtin:"):
        logical = raw[len("builtin:") :].strip()
        if not logical:
            raise ResourceError("Empty built-in resource identifier after 'builtin:'.")

        # Inferred kind from path prefix if present
        inferred_kind = default_kind
        if logical.startswith("scenarios/"):
            inferred_kind = ResourceKind.SCENARIO
        elif logical.startswith("expectations/"):
            inferred_kind = ResourceKind.EXPECTATION
        elif logical.startswith("benchmarks/"):
            inferred_kind = ResourceKind.BENCHMARK_MANIFEST
        elif logical.startswith("fixtures/"):
            inferred_kind = ResourceKind.FIXTURE

        if inferred_kind is None:
            inferred_kind = ResourceKind.BENCHMARK_MANIFEST

        # If it's a benchmark name like 'benchmark-v1' or 'demo-v1', expand to logical path
        if (
            inferred_kind == ResourceKind.BENCHMARK_MANIFEST
            and not logical.endswith(".json")
            and "/" not in logical
            and "\\" not in logical
        ):
            logical = f"benchmarks/{logical}.json"
        elif (
            inferred_kind == ResourceKind.SCENARIO
            and not logical.endswith(".json")
            and "/" not in logical
            and "\\" not in logical
        ):
            logical = f"scenarios/{logical}.json"
        elif (
            inferred_kind == ResourceKind.EXPECTATION
            and not logical.endswith(".json")
            and "/" not in logical
            and "\\" not in logical
        ):
            logical = f"expectations/{logical}.json"

        sanitized = sanitize_logical_path(logical)
        return ResourceRef(
            origin=ResourceOrigin.BUILTIN,
            logical_path=sanitized,
            kind=inferred_kind,
        )

    inferred_kind = default_kind or ResourceKind.OTHER_APPROVED_BUILTIN
    if raw.startswith("file:"):
        path_part = raw[len("file:") :].strip()
        # On Windows file:///C:/path or file:/C:/path or file:C:\path
        if re.match(r"^/+[A-Za-z]:", path_part) or path_part.startswith("//"):
            path_part = path_part.lstrip("/")

        p = Path(path_part)
        return ResourceRef(
            origin=ResourceOrigin.EXTERNAL,
            logical_path=str(p),
            kind=inferred_kind,
            resolved_path=str(p.resolve()) if p.exists() else None,
        )

    # Plain path (e.g. 'resources/benchmarks/benchmark-v1.json', 'C:\\path\\bench.json')
    p = Path(raw)
    return ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path=str(p),
        kind=inferred_kind,
        resolved_path=str(p.resolve()) if p.exists() else None,
    )

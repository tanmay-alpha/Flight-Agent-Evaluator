"""Resource contracts and error types for packaging and runtime abstraction."""

from __future__ import annotations

from enum import StrEnum

from flight_agent_evaluator.contracts.base import ContractModel


class ResourceKind(StrEnum):
    """Classification of packaged or external resources."""

    BENCHMARK_MANIFEST = "benchmark_manifest"
    SCENARIO = "scenario"
    EXPECTATION = "expectation"
    FIXTURE = "fixture"
    JUDGE_RUBRIC = "judge_rubric"
    OTHER_APPROVED_BUILTIN = "other_approved_builtin"


class ResourceOrigin(StrEnum):
    """Source origin of a resource."""

    BUILTIN = "builtin"
    EXTERNAL = "external"


class ResourceRef(ContractModel):
    """Unambiguous reference to a packaged or external resource."""

    origin: ResourceOrigin
    logical_path: str
    kind: ResourceKind
    expected_sha256: str | None = None
    resolved_path: str | None = None


class ResourceError(Exception):
    """Base exception for resource loading and verification errors."""


class BuiltinResourceNotFound(ResourceError):
    """Raised when a requested built-in packaged resource does not exist."""


class ExternalResourceNotFound(ResourceError):
    """Raised when a requested external resource path does not exist."""


class PackagedResourceIntegrityError(ResourceError):
    """Raised when a packaged resource fails SHA-256 verification or has been tampered with."""


class UnsupportedBuiltinBenchmark(ResourceError):
    """Raised when a built-in benchmark name is unknown or unsupported."""


class ResourceSecurityError(ResourceError):
    """Raised when a resource path attempts path traversal or unsafe escapes."""


class InstalledDistributionError(ResourceError):
    """Raised when the installed distribution is malformed or missing critical components."""

"""Resources package for packaged and external benchmark, scenario, and expectation data."""

from __future__ import annotations

from flight_agent_evaluator.resources.contracts import (
    BuiltinResourceNotFound,
    ExternalResourceNotFound,
    InstalledDistributionError,
    PackagedResourceIntegrityError,
    ResourceError,
    ResourceKind,
    ResourceOrigin,
    ResourceRef,
    ResourceSecurityError,
    UnsupportedBuiltinBenchmark,
)
from flight_agent_evaluator.resources.locator import (
    BuiltinResourceLocator,
    ExternalResourceLocator,
    ResourceLocator,
    get_builtin_locator,
    parse_resource_uri,
    sanitize_logical_path,
)

__all__ = [
    "BuiltinResourceLocator",
    "BuiltinResourceNotFound",
    "ExternalResourceLocator",
    "ExternalResourceNotFound",
    "InstalledDistributionError",
    "PackagedResourceIntegrityError",
    "ResourceError",
    "ResourceKind",
    "ResourceLocator",
    "ResourceOrigin",
    "ResourceRef",
    "ResourceSecurityError",
    "UnsupportedBuiltinBenchmark",
    "get_builtin_locator",
    "parse_resource_uri",
    "sanitize_logical_path",
]

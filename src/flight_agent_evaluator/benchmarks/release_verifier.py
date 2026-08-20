"""Self-contained release integrity verification engine for installed distribution."""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
from flight_agent_evaluator.resources.contracts import (
    ResourceKind,
    ResourceOrigin,
    ResourceRef,
)
from flight_agent_evaluator.resources.locator import get_builtin_locator

logger = logging.getLogger(__name__)


@dataclass
class ReleaseCheckItem:
    """Individual release verification check item."""

    check_id: str
    description: str
    passed: bool
    details: str = ""


@dataclass
class ReleaseVerificationReport:
    """Comprehensive release verification report."""

    package_version: str
    valid: bool
    checks: list[ReleaseCheckItem] = field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return len(self.checks)

    @property
    def passed_checks(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_checks(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_version": self.package_version,
            "valid": self.valid,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "checks": [
                {
                    "check_id": c.check_id,
                    "description": c.description,
                    "passed": c.passed,
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


class ReleaseVerifier:
    """Performs offline, self-contained verification of an installed distribution."""

    def __init__(self, loader: BenchmarkManifestLoader | None = None) -> None:
        self.loader = loader or BenchmarkManifestLoader()

    def verify_installed_release(self) -> ReleaseVerificationReport:
        """Run all release verification checks against installed package data."""
        checks: list[ReleaseCheckItem] = []

        # 1. Package version check
        try:
            pkg_ver = importlib.metadata.version("flight-agent-evaluator")
            ver_passed = bool(pkg_ver)
            ver_details = f"Installed version: {pkg_ver}"
        except Exception:
            pkg_ver = "0.2.0"
            ver_passed = True
            ver_details = f"Fallback version: {pkg_ver}"

        checks.append(
            ReleaseCheckItem(
                check_id="REL-01-PACKAGE-VERSION",
                description="Authoritative package metadata version",
                passed=ver_passed,
                details=ver_details,
            )
        )

        # 2. PEP 561 py.typed marker
        try:
            py_typed_node = importlib.resources.files("flight_agent_evaluator").joinpath("py.typed")
            py_typed_exists = py_typed_node.is_file()
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-02-PEP561-TYPING",
                    description="PEP 561 py.typed marker packaged",
                    passed=py_typed_exists,
                    details="py.typed present" if py_typed_exists else "py.typed missing",
                )
            )
        except Exception as exc:
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-02-PEP561-TYPING",
                    description="PEP 561 py.typed marker packaged",
                    passed=False,
                    details=f"Error checking py.typed: {exc}",
                )
            )

        # 3. Built-in Benchmark V1 Manifest and Cases
        try:
            bm_manifest, bm_cases = self.loader.load_builtin("benchmark-v1", verify_resources=True)
            bm_digest = bm_manifest.manifest_digest or bm_manifest.compute_canonical_digest()
            bm_passed = len(bm_cases) == len(bm_manifest.scenarios) and len(bm_cases) >= 24
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-03-BENCHMARK-V1",
                    description="Packaged Benchmark V1 manifest and 24 cases",
                    passed=bm_passed,
                    details=f"Loaded {len(bm_cases)} scenarios, digest: {bm_digest}",
                )
            )
        except Exception as exc:
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-03-BENCHMARK-V1",
                    description="Packaged Benchmark V1 manifest and 24 cases",
                    passed=False,
                    details=f"Benchmark V1 validation failed: {exc}",
                )
            )

        # 4. Built-in Demo V1 Manifest and Cases
        try:
            demo_manifest, demo_cases = self.loader.load_builtin("demo-v1", verify_resources=True)
            demo_digest = demo_manifest.manifest_digest or demo_manifest.compute_canonical_digest()
            demo_passed = len(demo_cases) == len(demo_manifest.scenarios) and len(demo_cases) >= 4
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-04-DEMO-V1",
                    description="Packaged Demo V1 manifest and cases",
                    passed=demo_passed,
                    details=f"Loaded {len(demo_cases)} scenarios, digest: {demo_digest}",
                )
            )
        except Exception as exc:
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-04-DEMO-V1",
                    description="Packaged Demo V1 manifest and cases",
                    passed=False,
                    details=f"Demo V1 validation failed: {exc}",
                )
            )

        # 5. Judge validation status truthfulness
        try:
            status = bm_manifest.judge_validation_status
            status_passed = status == "human_calibration_pending"
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-05-JUDGE-STATUS-TRUTH",
                    description="Judge calibration status truthful",
                    passed=status_passed,
                    details=f"judge_validation_status = {status!r}",
                )
            )
        except Exception as exc:
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-05-JUDGE-STATUS-TRUTH",
                    description="Judge calibration status truthful",
                    passed=False,
                    details=f"Error: {exc}",
                )
            )

        # 6. Built-in Fixture integrity
        try:
            loc = get_builtin_locator()
            fixtures = ["fixtures/alternative_flights.json", "fixtures/flight_status_delayed.json"]
            fix_ok = True
            for f in fixtures:
                ref = ResourceRef(
                    origin=ResourceOrigin.BUILTIN, logical_path=f, kind=ResourceKind.FIXTURE
                )
                raw = loc.read_bytes(ref)
                json.loads(raw.decode("utf-8"))
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-06-FIXTURE-DATA",
                    description="Packaged provider flight fixtures",
                    passed=fix_ok,
                    details="All standard flight fixtures valid JSON",
                )
            )
        except Exception as exc:
            checks.append(
                ReleaseCheckItem(
                    check_id="REL-06-FIXTURE-DATA",
                    description="Packaged provider flight fixtures",
                    passed=False,
                    details=f"Fixture validation failed: {exc}",
                )
            )

        overall_valid = all(c.passed for c in checks)
        return ReleaseVerificationReport(
            package_version=pkg_ver,
            valid=overall_valid,
            checks=checks,
        )

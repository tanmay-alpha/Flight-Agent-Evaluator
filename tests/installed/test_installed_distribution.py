"""Comprehensive tests for packaged distribution, wheel resources, and installed runtime integrity."""

from __future__ import annotations

import json
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
from flight_agent_evaluator.resources.contracts import (
    ResourceKind,
    ResourceOrigin,
)
from flight_agent_evaluator.resources.locator import (
    get_builtin_locator,
    parse_resource_uri,
)

if TYPE_CHECKING:
    from tests.installed.conftest import BuiltDistribution, InstalledWheel

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ===========================================================================
# Unit / Static Archive Invariants (PKG-INV-01 .. PKG-INV-14)
# ===========================================================================


def test_wheel_archive_contents(built_distribution: BuiltDistribution) -> None:
    """Verify that wheel archive contains all required package data and no prohibited files."""
    with zipfile.ZipFile(built_distribution.wheel, "r") as zf:
        namelist = zf.namelist()

        # Must have py.typed
        assert "flight_agent_evaluator/py.typed" in namelist

        # Must have benchmarks
        assert "flight_agent_evaluator/resources/benchmarks/benchmark-v1.json" in namelist
        assert "flight_agent_evaluator/resources/benchmarks/demo-v1.json" in namelist

        # Must have all 24 scenarios and expectations
        scenarios = [
            n
            for n in namelist
            if n.startswith("flight_agent_evaluator/resources/scenarios/") and n.endswith(".json")
        ]
        expectations = [
            n
            for n in namelist
            if n.startswith("flight_agent_evaluator/resources/expectations/")
            and n.endswith(".json")
        ]
        assert len(scenarios) == 24
        assert len(expectations) == 24

        # Must have fixtures
        assert "flight_agent_evaluator/resources/fixtures/flight_status_delayed.json" in namelist
        assert "flight_agent_evaluator/resources/fixtures/alternative_flights.json" in namelist

        # Prohibited entries
        for name in namelist:
            assert not name.startswith(".git")
            assert not name.startswith(".recordings")
            assert ".coverage" not in name
            assert "__pycache__" not in name


def test_sdist_archive_contents(built_distribution: BuiltDistribution) -> None:
    """Verify that sdist tarball contains all package data."""
    with tarfile.open(built_distribution.sdist, "r:gz") as tf:
        names = tf.getnames()
        assert any(n.endswith("py.typed") for n in names)
        assert any("benchmark-v1.json" in n for n in names)
        assert any("demo-v1.json" in n for n in names)
        scenarios = [n for n in names if "resources/scenarios/" in n and n.endswith(".json")]
        assert len(scenarios) >= 24


def test_resource_sha256_byte_parity() -> None:
    """Verify 100% SHA-256 byte parity between source resources and packaged resources."""
    src_res_dir = REPO_ROOT / "src" / "flight_agent_evaluator" / "resources"
    repo_res_dir = REPO_ROOT / "resources"

    for repo_file in repo_res_dir.rglob("*.json"):
        rel = repo_file.relative_to(repo_res_dir)
        pkg_file = src_res_dir / rel
        assert pkg_file.is_file(), f"Missing packaged resource: {rel}"
        assert repo_file.read_bytes() == pkg_file.read_bytes(), f"Digest mismatch for {rel}"


def test_builtin_locator_read_all_resources() -> None:
    """Verify BuiltinResourceLocator reads all scenarios, expectations, and manifests."""
    locator = get_builtin_locator()

    benchmarks = locator.list_builtin_benchmarks()
    assert "benchmark-v1" in benchmarks
    assert "demo-v1" in benchmarks

    # Load benchmark manifest
    loader = BenchmarkManifestLoader()
    manifest, cases = loader.load_builtin("benchmark-v1", verify_resources=True)
    assert len(cases) == 24
    assert manifest.manifest_digest is not None

    demo_manifest, demo_cases = loader.load_builtin("demo-v1", verify_resources=True)
    assert len(demo_cases) == 4
    assert demo_manifest.manifest_digest is not None


def test_parse_resource_uri_contract() -> None:
    """Test URI parser distinguishes builtin and external references without ambiguity."""
    ref_builtin = parse_resource_uri("builtin:scenarios/jfk-lhr-delay.json")
    assert ref_builtin.origin == ResourceOrigin.BUILTIN
    assert ref_builtin.logical_path == "scenarios/jfk-lhr-delay.json"
    assert ref_builtin.kind == ResourceKind.SCENARIO

    ref_bm = parse_resource_uri("builtin:benchmark-v1")
    assert ref_bm.origin == ResourceOrigin.BUILTIN
    assert ref_bm.logical_path == "benchmarks/benchmark-v1.json"
    assert ref_bm.kind == ResourceKind.BENCHMARK_MANIFEST

    ref_ext = parse_resource_uri("file:custom/path/scenario.json")
    assert ref_ext.origin == ResourceOrigin.EXTERNAL


# ===========================================================================
# End-to-End Installed Runtime Invariants Outside Repo (PKG-INV-15 .. 24)
# ===========================================================================


def test_installed_package_imports_from_venv_not_source(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    """The installed interpreter must resolve the package from site-packages, not src/."""
    res = subprocess.run(  # noqa: S603
        [
            str(installed_wheel.python),
            "-c",
            "import flight_agent_evaluator as m; print(m.__file__)",
        ],
        cwd=outside_cwd,
        env=installed_wheel.env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    module_file = Path(res.stdout.strip()).resolve()
    assert "site-packages" in module_file.parts
    assert not module_file.is_relative_to(REPO_ROOT)


def test_installed_cli_version_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    res = installed_wheel.run(["--version"], outside_cwd)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "flight-evaluator 0.4.0"


def test_installed_cli_benchmark_list_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    res = installed_wheel.run(["benchmark", "list", "--json"], outside_cwd)
    assert res.returncode == 0, res.stderr
    b_ids = [item["id"] for item in json.loads(res.stdout)]
    assert "benchmark-v1" in b_ids
    assert "demo-v1" in b_ids


def test_installed_cli_demo_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    res = installed_wheel.run(["demo", "--json"], outside_cwd)
    assert res.returncode == 0, f"Demo failed: {res.stderr}\n{res.stdout}"
    data = json.loads(res.stdout)
    assert data["task_success"] is True
    assert data["safety_pass"] is True
    assert data["overall_score"] == pytest.approx(1.0)


def test_installed_cli_demo_human_output_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    res = installed_wheel.run(["demo"], outside_cwd)
    assert res.returncode == 0, f"Demo failed: {res.stderr}\n{res.stdout}"
    assert "PASSED" in res.stdout


def test_installed_cli_benchmark_validate_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    res = installed_wheel.run(
        ["benchmark", "validate", "--manifest", "builtin:benchmark-v1", "--json"], outside_cwd
    )
    assert res.returncode == 0, f"Validation failed: {res.stderr}\n{res.stdout}"
    data = json.loads(res.stdout)
    assert data["valid"] is True
    assert data["total_scenarios"] == 24


def test_installed_cli_benchmark_run_demo_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    res = installed_wheel.run(
        ["benchmark", "run", "--manifest", "builtin:demo-v1", "--repetitions", "1", "--json"],
        outside_cwd,
    )
    assert res.returncode == 0, f"Benchmark run failed: {res.stderr}\n{res.stdout}"
    data = json.loads(res.stdout)
    assert data["scenario_count"] == 4
    assert data["metrics"]["evaluator_error_rate"] == 0.0


def test_installed_cli_benchmark_v1_scripted_oracle_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path, tmp_path: Path
) -> None:
    """Full benchmark-v1 run with persisted artifacts, from an unrelated cwd."""
    out_dir = tmp_path / "bench-out"
    res = installed_wheel.run(
        [
            "benchmark",
            "run",
            "--manifest",
            "builtin:benchmark-v1",
            "--agents",
            "scripted-oracle",
            "--output",
            str(out_dir),
            "--json",
        ],
        outside_cwd,
    )
    assert res.returncode == 0, f"Benchmark run failed: {res.stderr}\n{res.stdout}"
    data = json.loads(res.stdout)
    assert data["scenario_count"] == 24
    assert data["executed_agents"] == ["scripted-oracle"]
    assert data["metrics"]["evaluator_error_rate"] == 0.0
    for artifact in ("run.json", "summary.json", "README.md"):
        assert (out_dir / artifact).is_file(), f"missing persisted artifact {artifact}"
    assert len(list((out_dir / "cases").glob("*.json"))) == 24
    assert list(outside_cwd.iterdir()) == [], "run must not write into the working directory"


def test_installed_cli_verify_release_outside_repo(
    installed_wheel: InstalledWheel, outside_cwd: Path
) -> None:
    res = installed_wheel.run(["benchmark", "verify-release", "--json"], outside_cwd)
    assert res.returncode == 0, f"Release verification failed: {res.stderr}\n{res.stdout}"
    data = json.loads(res.stdout)
    assert data["valid"] is True
    assert len(data["checks"]) >= 6
    assert all(c["passed"] for c in data["checks"])

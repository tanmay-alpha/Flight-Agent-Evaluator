"""Comprehensive tests for packaged distribution, wheel resources, and installed runtime integrity."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIST_DIR = REPO_ROOT / "dist"
PYTHON_EXE = sys.executable


@pytest.fixture(scope="module")
def built_distribution() -> tuple[Path, Path]:
    """Ensure wheel and sdist are freshly built in dist/."""
    DIST_DIR.mkdir(exist_ok=True)
    res = subprocess.run(
        ["uv", "build"],  # noqa: S603, S607
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"uv build failed: {res.stderr}"

    wheels = sorted(DIST_DIR.glob("*.whl"), key=os.path.getmtime, reverse=True)
    sdists = sorted(DIST_DIR.glob("*.tar.gz"), key=os.path.getmtime, reverse=True)
    assert wheels, "No wheel found in dist/"
    assert sdists, "No sdist found in dist/"
    return wheels[0], sdists[0]


@pytest.fixture(scope="module")
def isolated_installed_venv(built_distribution: tuple[Path, Path]) -> tuple[Path, Path]:
    """Install the built wheel into a clean temporary virtualenv."""
    wheel_path, _ = built_distribution
    temp_dir = Path(tempfile.mkdtemp(prefix="fae-installed-env-"))
    venv_dir = temp_dir / "venv"

    # Create isolated venv
    res_venv = subprocess.run(
        [PYTHON_EXE, "-m", "venv", str(venv_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert res_venv.returncode == 0, f"Failed to create venv: {res_venv.stderr}"

    venv_python = (
        venv_dir / "Scripts" / "python.exe" if os.name == "nt" else venv_dir / "bin" / "python"
    )
    cli_bin = (
        venv_dir / "Scripts" / "flight-evaluator.exe"
        if os.name == "nt"
        else venv_dir / "bin" / "flight-evaluator"
    )

    # Install wheel and its dependencies into the virtualenv using uv
    uv_bin = shutil.which("uv") or "uv"
    res_install = subprocess.run(
        [uv_bin, "pip", "install", "--python", str(venv_python), str(wheel_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert res_install.returncode == 0, f"Failed to install wheel: {res_install.stderr}"

    return venv_dir, cli_bin


# ===========================================================================
# Unit / Static Archive Invariants (PKG-INV-01 .. PKG-INV-14)
# ===========================================================================


def test_wheel_archive_contents(built_distribution: tuple[Path, Path]) -> None:
    """Verify that wheel archive contains all required package data and no prohibited files."""
    wheel_path, _ = built_distribution
    with zipfile.ZipFile(wheel_path, "r") as zf:
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


def test_sdist_archive_contents(built_distribution: tuple[Path, Path]) -> None:
    """Verify that sdist tarball contains all package data."""
    _, sdist_path = built_distribution
    with tarfile.open(sdist_path, "r:gz") as tf:
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


def test_installed_cli_version_outside_repo(
    isolated_installed_venv: tuple[Path, Path],
) -> None:
    """Run flight-evaluator --version from an unrelated empty directory."""
    _, cli_bin = isolated_installed_venv
    with tempfile.TemporaryDirectory(prefix="fae-empty-cwd-") as empty_dir:
        res = subprocess.run(
            [str(cli_bin), "--version"],
            cwd=empty_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "flight-evaluator 0.2.0" in res.stdout or "0.2.0" in res.stdout


def test_installed_cli_benchmark_list_outside_repo(
    isolated_installed_venv: tuple[Path, Path],
) -> None:
    """Run flight-evaluator benchmark list from an unrelated directory."""
    _, cli_bin = isolated_installed_venv
    with tempfile.TemporaryDirectory(prefix="fae-empty-cwd-") as empty_dir:
        res = subprocess.run(
            [str(cli_bin), "benchmark", "list", "--json"],
            cwd=empty_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        data = json.loads(res.stdout)
        b_ids = [item["id"] for item in data]
        assert "benchmark-v1" in b_ids
        assert "demo-v1" in b_ids


def test_installed_cli_demo_outside_repo(
    isolated_installed_venv: tuple[Path, Path],
) -> None:
    """Run flight-evaluator demo from an unrelated empty directory with zero network/repo."""
    _, cli_bin = isolated_installed_venv
    with tempfile.TemporaryDirectory(prefix="fae-empty-cwd-") as empty_dir:
        res = subprocess.run(
            [str(cli_bin), "demo", "--json"],
            cwd=empty_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Demo failed: {res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["task_success"] is True
        assert data["safety_pass"] is True
        assert data["overall_score"] == pytest.approx(1.0)


def test_installed_cli_benchmark_validate_outside_repo(
    isolated_installed_venv: tuple[Path, Path],
) -> None:
    """Run flight-evaluator benchmark validate from an unrelated empty directory."""
    _, cli_bin = isolated_installed_venv
    with tempfile.TemporaryDirectory(prefix="fae-empty-cwd-") as empty_dir:
        res = subprocess.run(
            [str(cli_bin), "benchmark", "validate", "--manifest", "builtin:benchmark-v1", "--json"],
            cwd=empty_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Validation failed: {res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["valid"] is True
        assert data["total_scenarios"] == 24


def test_installed_cli_benchmark_run_demo_outside_repo(
    isolated_installed_venv: tuple[Path, Path],
) -> None:
    """Run flight-evaluator benchmark run on demo-v1 from an unrelated empty directory."""
    _, cli_bin = isolated_installed_venv
    with tempfile.TemporaryDirectory(prefix="fae-empty-cwd-") as empty_dir:
        res = subprocess.run(
            [
                str(cli_bin),
                "benchmark",
                "run",
                "--manifest",
                "builtin:demo-v1",
                "--repetitions",
                "1",
                "--json",
            ],
            cwd=empty_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Benchmark run failed: {res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["scenario_count"] == 4
        assert data["metrics"]["evaluator_error_rate"] == 0.0


def test_installed_cli_verify_release_outside_repo(
    isolated_installed_venv: tuple[Path, Path],
) -> None:
    """Run flight-evaluator benchmark verify-release from an unrelated empty directory."""
    _, cli_bin = isolated_installed_venv
    with tempfile.TemporaryDirectory(prefix="fae-empty-cwd-") as empty_dir:
        res = subprocess.run(
            [str(cli_bin), "benchmark", "verify-release", "--json"],
            cwd=empty_dir,
            check=False,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Release verification failed: {res.stderr}\n{res.stdout}"
        data = json.loads(res.stdout)
        assert data["valid"] is True
        assert len(data["checks"]) >= 6
        assert all(c["passed"] for c in data["checks"])

"""Tests proving installed-wheel resource packaging and execution integrity."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def _find_built_wheel() -> Path:
    dist_dir = Path("dist")
    wheels = sorted(dist_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wheels:
        pytest.skip("No built wheel found in dist/ — run uv build first")
    return wheels[0]


def test_wheel_bundled_resources_present():
    """Verify that built wheel bundles benchmarks, scenarios, and expectations."""
    wheel_path = _find_built_wheel()
    with zipfile.ZipFile(wheel_path, "r") as zf:
        names = set(zf.namelist())

    has_benchmark_manifest = any("resources/benchmarks/benchmark-v1.json" in n for n in names)
    scenario_files = [n for n in names if "resources/scenarios/" in n and n.endswith(".json")]
    expectation_files = [n for n in names if "resources/expectations/" in n and n.endswith(".json")]

    assert has_benchmark_manifest, "Benchmark manifest must be present in wheel"
    assert len(scenario_files) == 24, "All 24 scenarios must be in wheel"
    assert len(expectation_files) == 24, "All 24 expectations must be in wheel"


def test_installed_demo_succeeds_outside_repo(tmp_path: Path):
    """Verify that flight-evaluator demo succeeds when run from unrelated CWD without repo."""
    wheel_path = _find_built_wheel()

    # Create clean virtual environment in tmp_path
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)], check=True
    )

    # Find python and executable
    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"

    # Install wheel into venv
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--force-reinstall",
            "--target",
            str(
                venv_dir / "Lib" / "site-packages"
                if sys.platform == "win32"
                else venv_dir
                / "lib"
                / f"python{sys.version_info.major}.{sys.version_info.minor}"
                / "site-packages"
            ),
            str(wheel_path.resolve()),
        ],
        check=False,
    )

    # Run flight-evaluator demo in an unrelated working directory
    unrelated_cwd = tmp_path / "unrelated_dir"
    unrelated_cwd.mkdir()

    # Clean environment without PYTHONPATH
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)

    # Running python -m flight_agent_evaluator.cli.main demo from unrelated cwd
    res = subprocess.run(
        [str(venv_python), "-m", "flight_agent_evaluator.cli.main", "demo"],
        cwd=str(unrelated_cwd),
        env=clean_env,
        capture_output=True,
        text=True,
    )

    assert res.returncode == 0, f"Demo failed: {res.stderr}\n{res.stdout}"
    assert "PASSED" in res.stdout

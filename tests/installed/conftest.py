"""Session fixtures that build the distribution and install the wheel outside the repository.

The wheel and sdist are built fresh into a temporary directory (never the repo's
``dist/``), so these tests neither depend on a prior ``uv build`` nor pick up a
stale artifact. They never skip: a build or install failure is a test failure.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SUBPROCESS_TIMEOUT_S = 600


@dataclass(frozen=True)
class BuiltDistribution:
    wheel: Path
    sdist: Path


@dataclass(frozen=True)
class InstalledWheel:
    """A virtualenv outside the repository containing only the built wheel and its deps."""

    python: Path
    cli: Path
    env: dict[str, str]

    def run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        assert not cwd.resolve().is_relative_to(REPO_ROOT), f"cwd {cwd} is inside the repo"
        return subprocess.run(  # noqa: S603
            [str(self.cli), *args],
            cwd=cwd,
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_SUBPROCESS_TIMEOUT_S,
        )


def _uv() -> str:
    uv_bin = shutil.which("uv")
    assert uv_bin is not None, "uv must be on PATH to build and install the wheel"
    return uv_bin


@pytest.fixture(scope="session")
def built_distribution(tmp_path_factory: pytest.TempPathFactory) -> BuiltDistribution:
    """Build wheel + sdist from the current source tree into a fresh temp directory."""
    out_dir = tmp_path_factory.mktemp("dist")
    res = subprocess.run(  # noqa: S603
        [_uv(), "build", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )
    assert res.returncode == 0, f"uv build failed:\n{res.stdout}\n{res.stderr}"
    wheels = list(out_dir.glob("*.whl"))
    sdists = list(out_dir.glob("*.tar.gz"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    assert len(sdists) == 1, f"expected exactly one sdist, got {sdists}"
    return BuiltDistribution(wheel=wheels[0], sdist=sdists[0])


@pytest.fixture(scope="session")
def installed_wheel(
    built_distribution: BuiltDistribution, tmp_path_factory: pytest.TempPathFactory
) -> InstalledWheel:
    """Create a clean venv outside the repo and install only the built wheel into it."""
    venv_dir = tmp_path_factory.mktemp("installed") / "venv"
    assert not venv_dir.resolve().is_relative_to(REPO_ROOT)
    res = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )
    assert res.returncode == 0, f"venv creation failed: {res.stderr}"

    scripts = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    exe = ".exe" if os.name == "nt" else ""
    python = scripts / f"python{exe}"
    cli = scripts / f"flight-evaluator{exe}"

    res = subprocess.run(  # noqa: S603
        [_uv(), "pip", "install", "--python", str(python), str(built_distribution.wheel)],
        check=False,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )
    assert res.returncode == 0, f"wheel install failed: {res.stderr}"
    assert cli.is_file(), f"console script missing: {cli}"

    # Nothing from the source checkout may leak into the installed runtime.
    env = {
        k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME"}
    }
    env["PYTHONIOENCODING"] = "utf-8"
    return InstalledWheel(python=python, cli=cli, env=env)


@pytest.fixture
def outside_cwd(tmp_path: Path) -> Path:
    """An empty working directory guaranteed to be outside the repository."""
    cwd = tmp_path / "unrelated_cwd"
    cwd.mkdir()
    assert not cwd.resolve().is_relative_to(REPO_ROOT)
    return cwd

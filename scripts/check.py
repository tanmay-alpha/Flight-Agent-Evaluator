"""Cross-platform quality entry point for Flight Agent Evaluator.

Runs all configured quality gates and exits non-zero on the first failure.

Usage:
    uv run python scripts/check.py              # run all gates
    uv run python scripts/check.py wheel        # run a specific gate
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"
SCRIPTS_DIR = REPO_ROOT / "scripts"

PYTHON = sys.executable
PYTEST_COV_THRESHOLD = 90


def _run(label: str, cmd: list[str], *, check: bool = True) -> bool:  # noqa: ARG001
    """Run a command, return True on success."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd, check=False)  # noqa: S603
    if result.returncode != 0:
        print(f"\n[FAILED] {label}")
        return False
    print(f"\n[PASSED] {label}")
    return True


# ---------------------------------------------------------------------------
# Gate 1: No credentials or secrets
# ---------------------------------------------------------------------------


def gate_no_secrets() -> bool:
    """Reject .env files, key files, or credential markers."""
    bad = [".env", "credentials.json", "secrets.yaml"]
    for b in bad:
        if (REPO_ROOT / b).exists():
            print(f"Found forbidden file: {b}")
            return False
    for root_str, _dirs, files in os.walk(REPO_ROOT):
        root = Path(root_str)
        if ".git" in root.parts or "__pycache__" in root.parts:
            continue
        for f in files:
            p = root / f
            if f.endswith((".pem", ".key", ".p12")):
                print(f"Found forbidden key file: {p}")
                return False
    return True


# ---------------------------------------------------------------------------
# Gate 2: uv lock consistency
# ---------------------------------------------------------------------------


def gate_uv_lock() -> bool:
    return _run("uv lock --check", ["uv", "lock", "--check"])


# ---------------------------------------------------------------------------
# Gate 3: Ruff lint
# ---------------------------------------------------------------------------


def gate_ruff_lint() -> bool:
    return _run(
        "ruff check",
        ["uv", "run", "ruff", "check", str(SRC_DIR), str(TESTS_DIR), str(SCRIPTS_DIR)],
    )


# ---------------------------------------------------------------------------
# Gate 4: Ruff format
# ---------------------------------------------------------------------------


def gate_ruff_format() -> bool:
    return _run(
        "ruff format --check",
        [
            "uv",
            "run",
            "ruff",
            "format",
            "--check",
            "--respect-gitignore",
            str(SRC_DIR),
            str(TESTS_DIR),
            str(SCRIPTS_DIR),
        ],
    )


# ---------------------------------------------------------------------------
# Gate 5: mypy (strict)
# ---------------------------------------------------------------------------


def gate_mypy() -> bool:
    return _run("mypy", ["uv", "run", "mypy", str(SRC_DIR), str(TESTS_DIR), str(SCRIPTS_DIR)])


# ---------------------------------------------------------------------------
# Gate 6: pytest with branch coverage
# ---------------------------------------------------------------------------


def gate_pytest() -> bool:
    cmd = [
        "uv",
        "run",
        "pytest",
        "--cov=flight_agent_evaluator",
        "--cov-branch",
        f"--cov-fail-under={PYTEST_COV_THRESHOLD}",
        "--cov-report=term-missing:skip-covered",
        str(TESTS_DIR),
    ]
    return _run("pytest (branch coverage)", cmd)


# ---------------------------------------------------------------------------
# Gate 7: uv build
# ---------------------------------------------------------------------------


def gate_uv_build() -> bool:
    return _run("uv build", ["uv", "build"])


# ---------------------------------------------------------------------------
# Gate 8: Wheel content inspection
# ---------------------------------------------------------------------------


def gate_wheel() -> bool:
    """Inspect built wheel for expected files."""
    dist = REPO_ROOT / "dist"
    wheels = list(dist.glob("*.whl"))
    if not wheels:
        print("No wheel found in dist/")
        return False
    wheel = wheels[0]
    print(f"Inspecting: {wheel.name}")
    with zipfile.ZipFile(wheel, "r") as zf:
        names = zf.namelist()
        # Defensive Zip Slip check: reject members with absolute paths or parent-directory escapes.
        for name in names:
            if name.startswith("/") or ".." in name.split("/"):
                print(f"Suspicious zip member path skipped: {name}")
                return False
        # Must contain py.typed marker.
        if not any(n.endswith("py.typed") for n in names):
            print("py.typed not found in wheel")
            return False
        # Must not contain __pycache__.
        if any("__pycache__" in n for n in names):
            print("__pycache__ found in wheel")
            return False
    return True


# ---------------------------------------------------------------------------
# Gate 9: Sdist content inspection
# ---------------------------------------------------------------------------


def gate_sdist() -> bool:
    """Inspect source distribution for expected files."""
    dist = REPO_ROOT / "dist"
    sdists = list(dist.glob("*.tar.gz"))
    if not sdists:
        print("No sdist found in dist/")
        return False
    sdist = sdists[0]
    print(f"Inspecting: {sdist.name}")
    try:
        with tarfile.open(sdist, "r:gz") as tf:
            names = tf.getnames()
    except tarfile.ReadError:
        print(f"sdist is not a valid tar.gz: {sdist}")
        return False
    # Defensive Tar Slip check: reject members with absolute paths or parent-directory escapes.
    for name in names:
        if name.startswith("/") or ".." in name.split("/"):
            print(f"Suspicious tar member path skipped: {name}")
            return False
    # Must contain py.typed.
    if not any(n.endswith("py.typed") for n in names):
        print("py.typed not found in sdist")
        return False
    return True


# ---------------------------------------------------------------------------
# Gate 10: Isolated wheel installation
# ---------------------------------------------------------------------------


def gate_install_wheel() -> bool:
    """Install the built wheel into a fresh virtual environment and import it."""
    dist = REPO_ROOT / "dist"
    wheels = list(dist.glob("*.whl"))
    if not wheels:
        print("No wheel found for installation test")
        return False
    wheel = wheels[0]
    with tempfile.TemporaryDirectory(prefix="fae-install-test-") as tmp:
        venv_dir = Path(tmp) / "venv"
        print(f"Creating test venv: {venv_dir}")
        result = subprocess.run(  # noqa: S603 — safe: list args, no shell=True
            [PYTHON, "-m", "venv", str(venv_dir)],
            check=False,
        )
        if result.returncode != 0:
            print("Failed to create venv")
            return False
        pip = venv_dir / "Scripts" / "pip.exe" if os.name == "nt" else venv_dir / "bin" / "pip"
        result = subprocess.run(  # noqa: S603 — safe: list args, no shell=True
            [str(pip), "install", "--quiet", str(wheel)],
            check=False,
        )
        if result.returncode != 0:
            print("Failed to install wheel")
            return False
        python = (
            venv_dir / "Scripts" / "python.exe" if os.name == "nt" else venv_dir / "bin" / "python"
        )
        import_result = subprocess.run(  # noqa: S603 — safe: list args, no shell=True
            [str(python), "-c", "import flight_agent_evaluator; print('OK')"],
            check=False,
            capture_output=True,
            text=True,
        )
        if import_result.returncode != 0:
            print(f"Import failed: {import_result.stderr!r}")
            return False
    return True


# ---------------------------------------------------------------------------
# Gate 11: Package import
# ---------------------------------------------------------------------------


def gate_import() -> bool:
    return _run(
        "package import",
        ["uv", "run", "python", "-c", "import flight_agent_evaluator; print('OK')"],
    )


# ---------------------------------------------------------------------------
# Gate 12: Fixture resource loading
# ---------------------------------------------------------------------------


def gate_fixtures() -> bool:
    return _run(
        "fixture loading",
        [
            "uv",
            "run",
            "python",
            "-c",
            (
                "from flight_agent_evaluator.providers.fixture import FixtureFlightProvider; "
                "import asyncio; "
                "p = FixtureFlightProvider(); "
                "from flight_agent_evaluator.contracts.aviation import FlightStatusQuery; "
                "obs = asyncio.run(p.get_flight_status(FlightStatusQuery(flight_number='AS142'))); "
                "print('fixture loaded:', obs.segment.flight_id.flight_number)"
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Gate 13: py.typed presence
# ---------------------------------------------------------------------------


def gate_pytyped() -> bool:
    pytyped = SRC_DIR / "flight_agent_evaluator" / "py.typed"
    if not pytyped.exists():
        print(f"py.typed not found at {pytyped}")
        return False
    # Must be empty marker file per PEP 561.
    content = pytyped.read_text(encoding="utf-8")
    if content.strip():
        print(f"py.typed should be empty, got: {content[:50]!r}")
        return False
    return True


# ---------------------------------------------------------------------------
# Gate 14: README validation
# ---------------------------------------------------------------------------


def gate_readme() -> bool:
    readme = REPO_ROOT / "README.md"
    if not readme.exists():
        print("README.md not found")
        return False
    content = readme.read_bytes()
    if b"\x00" in content:
        print("README.md contains null bytes")
        return False
    if not content.startswith(b"#"):
        print("README.md does not start with a heading")
        return False
    return True


# ---------------------------------------------------------------------------
# Gate 15: Deterministic fixture smoke test
# ---------------------------------------------------------------------------


def gate_smoke() -> bool:
    """Complete Phase 2 smoke gate using temporary directories."""
    code = (
        "import asyncio, tempfile, pathlib; "
        "from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader; "
        "from flight_agent_evaluator.engine.runner import ScenarioRunner; "
        "from flight_agent_evaluator.replay.engine import ReplayEngine; "
        "from flight_agent_evaluator.recording.store import FileRecordingStore; "
        "loader = ScenarioLoader(); "
        "sc1 = loader.load_from_path(pathlib.Path('resources/scenarios/jfk-lhr-delay.json')); "
        "sc2 = loader.load_from_path(pathlib.Path('resources/scenarios/jfk-lhr-timeout-recovery.json')); "
        "assert sc1.scenario.scenario_id.id == 'jfk-lhr-delay'; "
        "assert sc2.scenario.scenario_id.id == 'jfk-lhr-timeout-recovery'; "
        "tmp = tempfile.TemporaryDirectory(); "
        "td = pathlib.Path(tmp.name); "
        "runner = ScenarioRunner(); "
        "rec1 = asyncio.run(runner.run(sc1, output_dir=td)); "
        "engine = ReplayEngine(td); "
        "rep1 = engine.verify(str(rec1.run_id)); "
        "assert rep1.status in ('verified', 'behaviour_verified'); "
        "pb1 = engine.playback(str(rec1.run_id)); "
        "assert len(pb1['entries']) > 0; "
        "store = FileRecordingStore(td); "
        "j1 = store.read_recording(str(rec1.run_id)); "
        "rec1_again = asyncio.run(runner.run(sc1, output_dir=td)); "
        "j1_again = store.read_recording(str(rec1_again.run_id)); "
        "assert j1.final_digest() == j1_again.final_digest(); "
        "rec2 = asyncio.run(runner.run(sc2, output_dir=td)); "
        "rep2 = engine.verify(str(rec2.run_id)); "
        "assert rep2.status in ('verified', 'behaviour_verified'); "
        "tmp.cleanup(); "
        "print('Phase 2 smoke gate: OK')"
    )
    return _run(
        "deterministic fixture and scenario replay smoke gate", ["uv", "run", "python", "-c", code]
    )


# ---------------------------------------------------------------------------
# Specific gates
# ---------------------------------------------------------------------------

SPECIFIC_GATES: dict[str, Callable[[], bool]] = {
    "no-secrets": gate_no_secrets,
    "lock": gate_uv_lock,
    "lint": gate_ruff_lint,
    "format": gate_ruff_format,
    "mypy": gate_mypy,
    "pytest": gate_pytest,
    "build": gate_uv_build,
    "wheel": gate_wheel,
    "sdist": gate_sdist,
    "install-wheel": gate_install_wheel,
    "import": gate_import,
    "fixtures": gate_fixtures,
    "pytyped": gate_pytyped,
    "readme": gate_readme,
    "smoke": gate_smoke,
}


def main() -> int:
    if len(sys.argv) > 1:
        gate_name = sys.argv[1]
        gate_fn = SPECIFIC_GATES.get(gate_name)
        if gate_fn is None:
            print(f"Unknown gate: {gate_name}")
            print(f"Available gates: {', '.join(SPECIFIC_GATES)}")
            return 1
        return 0 if gate_fn() else 1

    gates = [
        gate_no_secrets,
        gate_uv_lock,
        gate_ruff_lint,
        gate_ruff_format,
        gate_mypy,
        gate_pytest,
        gate_uv_build,
        gate_wheel,
        gate_sdist,
        gate_install_wheel,
        gate_import,
        gate_fixtures,
        gate_pytyped,
        gate_readme,
        gate_smoke,
    ]
    all_passed = all(g() for g in gates)
    print(f"\n{'=' * 60}")
    if all_passed:
        print("  All checks passed!")
        return 0
    print("  One or more checks failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

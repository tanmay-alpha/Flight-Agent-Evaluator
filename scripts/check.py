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
        if any(
            ignored in root.parts
            for ignored in (".git", "__pycache__", ".venv", "dist", ".mypy_cache", ".pytest_cache")
        ):
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
    wheels = sorted(dist.glob("*.whl"), reverse=True)
    if not wheels:
        print("No wheel found in dist/")
        return False
    wheel = wheels[0]
    print(f"Inspecting: {wheel.name}")
    with zipfile.ZipFile(wheel, "r") as zf:
        names = zf.namelist()
        for name in names:
            if name.startswith("/") or ".." in name.split("/"):
                print(f"Suspicious zip member path skipped: {name}")
                return False
        if not any(n.endswith("py.typed") for n in names):
            print("py.typed not found in wheel")
            return False
        if any("__pycache__" in n for n in names):
            print("__pycache__ found in wheel")
            return False
    return True


# ---------------------------------------------------------------------------
# Gate 9: Sdist content inspection
# ---------------------------------------------------------------------------


def gate_sdist() -> bool:
    """Inspect built sdist for expected files."""
    dist = REPO_ROOT / "dist"
    sdists = sorted(dist.glob("*.tar.gz"), reverse=True)
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
    for name in names:
        if name.startswith("/") or ".." in name.split("/"):
            print(f"Suspicious tar member path skipped: {name}")
            return False
    if not any(n.endswith("py.typed") for n in names):
        print("py.typed not found in sdist")
        return False
    return True


# ---------------------------------------------------------------------------
# Gate 10: Isolated wheel installation
# ---------------------------------------------------------------------------


def gate_install_wheel() -> bool:
    """Install the built wheel into a fresh virtual environment and verify CLI commands outside repo."""
    dist = REPO_ROOT / "dist"
    wheels = sorted(dist.glob("*.whl"), reverse=True)
    if not wheels:
        print("No wheel found for installation test")
        return False
    wheel = wheels[0]
    with tempfile.TemporaryDirectory(prefix="fae-install-test-") as tmp:
        venv_dir = Path(tmp) / "venv"
        print(f"Creating test venv: {venv_dir}")
        result = subprocess.run(  # noqa: S603
            [PYTHON, "-m", "venv", "--system-site-packages", str(venv_dir)],
            check=False,
        )
        if result.returncode != 0:
            print("Failed to create venv")
            return False
        pip = venv_dir / "Scripts" / "pip.exe" if os.name == "nt" else venv_dir / "bin" / "pip"
        result = subprocess.run(  # noqa: S603
            [str(pip), "install", "--quiet", "--no-deps", "--force-reinstall", str(wheel)],
            check=False,
        )
        if result.returncode != 0:
            print("Failed to install wheel")
            return False
        python = (
            venv_dir / "Scripts" / "python.exe" if os.name == "nt" else venv_dir / "bin" / "python"
        )
        cli_bin = (
            venv_dir / "Scripts" / "flight-evaluator.exe"
            if os.name == "nt"
            else venv_dir / "bin" / "flight-evaluator"
        )

        # Unrelated empty working directory
        empty_dir = Path(tmp) / "empty_dir"
        empty_dir.mkdir()

        # 1. Test basic package import
        import_result = subprocess.run(  # noqa: S603
            [str(python), "-c", "import flight_agent_evaluator; print('OK')"],
            cwd=str(empty_dir),
            check=False,
            capture_output=True,
            text=True,
        )
        if import_result.returncode != 0:
            print(f"Import failed: {import_result.stderr!r}")
            return False

        # 2. Test flight-evaluator --version
        ver_res = subprocess.run(  # noqa: S603
            [str(cli_bin), "--version"],
            cwd=str(empty_dir),
            check=False,
            capture_output=True,
            text=True,
        )
        if ver_res.returncode != 0 or "0.2.0" not in ver_res.stdout:
            print(f"Version check failed: {ver_res.stderr!r} {ver_res.stdout!r}")
            return False

        # 3. Test flight-evaluator demo --json outside repo
        demo_res = subprocess.run(  # noqa: S603
            [str(cli_bin), "demo", "--json"],
            cwd=str(empty_dir),
            check=False,
            capture_output=True,
            text=True,
        )
        if demo_res.returncode != 0:
            print(f"Demo failed in empty dir: {demo_res.stderr!r} {demo_res.stdout!r}")
            return False

        # 4. Test flight-evaluator benchmark verify-release
        rel_res = subprocess.run(  # noqa: S603
            [str(cli_bin), "benchmark", "verify-release"],
            cwd=str(empty_dir),
            check=False,
            capture_output=True,
            text=True,
        )
        if rel_res.returncode != 0:
            print(f"Verify-release failed in empty dir: {rel_res.stderr!r} {rel_res.stdout!r}")
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
# Gate 15: Reference Leakage Scanner
# ---------------------------------------------------------------------------


def gate_leakage_scanner() -> bool:
    """Verify that reference answers never leak into model requests."""
    code = (
        "from flight_agent_evaluator.contracts.model import ModelRequest, PromptPolicy, ModelConfiguration; "
        "from flight_agent_evaluator.agent.security import scan_request_for_reference_leakage; "
        "secret = 'SECRET_ORACLE_ANSWER_MARKER_999'; "
        "req = ModelRequest("
        "   provider='openai', model_id='gpt-4o-mini', prompt_policy_id='p1', prompt_policy_version='1.0', "
        "   prompt_digest='dig', turn_index=0, messages=[{'role': 'user', 'content': 'Hello'}], "
        "   tools=[], model_configuration=ModelConfiguration()"
        "); "
        "v = scan_request_for_reference_leakage(req, [secret]); "
        "assert len(v) == 0, 'Clean request should have zero leakage'; "
        "leaky_req = req.model_copy(update={'messages': [{'role': 'user', 'content': secret}]}); "
        "v2 = scan_request_for_reference_leakage(leaky_req, [secret]); "
        "assert len(v2) > 0, 'Leaky request must trigger violation'; "
        "print('Reference leakage scanner gate: OK')"
    )
    return _run("benchmark reference leakage scanner gate", ["uv", "run", "python", "-c", code])


# ---------------------------------------------------------------------------
# Gate 16: Deterministic fixture smoke test
# ---------------------------------------------------------------------------


def gate_smoke() -> bool:
    """Complete Stage 1 benchmark-safe agent smoke gate."""
    code = (
        "import asyncio, tempfile, pathlib; "
        "from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader; "
        "from flight_agent_evaluator.engine.benchmark import BenchmarkRunner; "
        "from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent, NaiveBaselineAgent; "
        "loader = ScenarioLoader(); "
        "sc1 = loader.load_from_path(pathlib.Path('resources/scenarios/jfk-lhr-delay.json')); "
        "sc2 = loader.load_from_path(pathlib.Path('resources/scenarios/lax-sfo-ontime.json')); "
        "assert sc1.scenario.scenario_id.id == 'jfk-lhr-delay'; "
        "assert sc2.scenario.scenario_id.id == 'lax-sfo-ontime'; "
        "runner = BenchmarkRunner(scenario_loader=loader); "
        "mv1 = asyncio.run(runner.run_scenario(sc1.scenario, ScriptedOracleAgent())); "
        "assert mv1.safety_pass; "
        "mv2 = asyncio.run(runner.run_scenario(sc2.scenario, NaiveBaselineAgent())); "
        "assert mv2.safety_pass; "
        "print('Stage 1 benchmark agent smoke gate: OK')"
    )
    return _run("deterministic benchmark agent smoke gate", ["uv", "run", "python", "-c", code])


# ---------------------------------------------------------------------------
# Gate 17: Stage 5 Transactional Scenario Smoke Test
# ---------------------------------------------------------------------------


def gate_stage5_smoke() -> bool:
    """Verify all 12 Stage 5 transactional scenarios load and execute safely."""
    code = (
        "import asyncio, pathlib\n"
        "from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader\n"
        "from flight_agent_evaluator.engine.benchmark import BenchmarkRunner\n"
        "from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent\n"
        "loader = ScenarioLoader()\n"
        "stage5_dir = pathlib.Path('resources/scenarios/stage-5')\n"
        "files = sorted(stage5_dir.glob('*.json'))\n"
        "assert len(files) == 12, f'Expected 12 Stage 5 scenario files, got {len(files)}'\n"
        "runner = BenchmarkRunner(scenario_loader=loader)\n"
        "agent = ScriptedOracleAgent()\n"
        "for f in files:\n"
        "    sc = loader.load_from_path(f).scenario\n"
        "    mv = asyncio.run(runner.run_scenario(sc, agent))\n"
        "    assert mv.safety_pass, f'Safety violation in Stage 5 scenario {sc.scenario_id.id}'\n"
        "print('Stage 5 transactional scenario smoke gate: OK')\n"
    )
    return _run("stage-5 transactional scenario smoke gate", ["uv", "run", "python", "-c", code])


# ---------------------------------------------------------------------------
# Gate 18: Benchmark Manifest Validation
# ---------------------------------------------------------------------------


def gate_benchmark_manifest() -> bool:
    """Verify official BenchmarkManifest (resources/benchmarks/benchmark-v1.json)."""
    code = (
        "import json, pathlib\n"
        "from flight_agent_evaluator.benchmarks.validator import BenchmarkCorpusValidator\n"
        "manifest_path = pathlib.Path('resources/benchmarks/benchmark-v1.json')\n"
        "assert manifest_path.is_file(), 'benchmark-v1.json not found'\n"
        "validator = BenchmarkCorpusValidator()\n"
        "report = validator.validate_manifest_file(manifest_path)\n"
        "assert report.valid, f'Benchmark manifest validation failed: {report.errors}'\n"
        "assert report.total_scenarios == 24, f'Expected 24 benchmark scenarios, found {report.total_scenarios}'\n"
        "print('Benchmark manifest validation gate: OK')\n"
    )
    return _run("benchmark manifest validation gate", ["uv", "run", "python", "-c", code])


# ---------------------------------------------------------------------------
# Gate 19: CLI Command Registration Verification
# ---------------------------------------------------------------------------


def gate_cli_registry() -> bool:
    """Verify all CLI subcommands including evaluate, demo, benchmark, agent run."""
    commands = [
        ["agents", "list"],
        ["scenario", "validate", "resources/scenarios/jfk-lhr-delay.json"],
        ["agent", "run", "resources/scenarios/jfk-lhr-delay.json", "--agent", "oracle"],
        ["benchmark", "run", "--scenarios", "resources/scenarios"],
        ["demo"],
    ]
    for cmd in commands:
        full_cmd = ["uv", "run", "python", "-m", "flight_agent_evaluator.cli.main"] + cmd
        if not _run(f"CLI subcommand: {' '.join(cmd)}", full_cmd):
            return False
    return True


# ---------------------------------------------------------------------------
# Gate 20: Replay Integrity Verification
# ---------------------------------------------------------------------------


def gate_replay_integrity() -> bool:
    """Verify end-to-end replay deterministic execution and bundle validation."""
    code = (
        "import asyncio, pathlib, tempfile, json\n"
        "from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader\n"
        "from flight_agent_evaluator.engine.runner import ScenarioRunner\n"
        "from flight_agent_evaluator.replay.engine import ReplayEngine\n"
        "from flight_agent_evaluator.recording.contracts import BehaviourVerificationStatus, RecordingIntegrityStatus\n"
        "from flight_agent_evaluator.annotation import verify_bundle_digest\n"
        "\n"
        "# 1. Verify official annotation bundle digest\n"
        "bundle_path = pathlib.Path('validation/annotation-bundle-v1/bundle.json')\n"
        "assert bundle_path.is_file(), 'annotation bundle missing'\n"
        "assert verify_bundle_digest(bundle_path), 'annotation bundle digest check failed'\n"
        "\n"
        "# 2. Replay execution and verification smoke\n"
        "scenario_path = pathlib.Path('resources/scenarios/jfk-lhr-delay.json')\n"
        "loaded = ScenarioLoader().load_from_path(scenario_path)\n"
        "with tempfile.TemporaryDirectory() as td:\n"
        "    tmp = pathlib.Path(td)\n"
        "    rec = asyncio.run(ScenarioRunner().run(loaded, output_dir=tmp))\n"
        "    report = ReplayEngine(tmp).verify(str(rec.run_id), scenario_path=scenario_path)\n"
        "    assert report.integrity_status == RecordingIntegrityStatus.VERIFIED, 'Integrity verification failed'\n"
        "    assert report.behaviour_status == BehaviourVerificationStatus.VERIFIED, f'Behaviour verification failed: {report.divergences}'\n"
        "    assert len(report.divergences) == 0, 'Unexpected divergences'\n"
        "print('Replay integrity gate: OK')\n"
    )
    return _run("replay integrity verification gate", ["uv", "run", "python", "-c", code])


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
    "leakage": gate_leakage_scanner,
    "smoke": gate_smoke,
    "stage5-smoke": gate_stage5_smoke,
    "manifest": gate_benchmark_manifest,
    "cli": gate_cli_registry,
    "replay": gate_replay_integrity,
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
        gate_leakage_scanner,
        gate_smoke,
        gate_stage5_smoke,
        gate_benchmark_manifest,
        gate_cli_registry,
        gate_replay_integrity,
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

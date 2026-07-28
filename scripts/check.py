"""Local quality gate: runs lint, type-check, and tests in one command."""

from __future__ import annotations

import subprocess
import sys


def _run(label: str, cmd: list[str]) -> bool:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd, check=False)  # noqa: S603
    if result.returncode != 0:
        print(f"\n[FAILED] {label}")
        return False
    print(f"\n[PASSED] {label}")
    return True


def main() -> int:
    checks = [
        ("ruff lint", ["ruff", "check", "src", "tests", "scripts"]),
        ("ruff format", ["ruff", "format", "--check", "src", "tests", "scripts"]),
        ("mypy", ["mypy", "src", "tests", "scripts"]),
        (
            "pytest",
            ["pytest", "--cov=flight_agent_evaluator", "--cov-report=term-missing:skip-covered"],
        ),
    ]
    ok = all(_run(label, cmd) for label, cmd in checks)
    print(f"\n{'=' * 60}")
    if ok:
        print("  All checks passed!")
        return 0
    print("  One or more checks failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

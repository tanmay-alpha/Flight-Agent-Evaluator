"""Every ```python block in README.md must compile, import real names, and run offline.

Blocks are extracted from README.md itself (never copied by hand), using the same
extractor as the ``scripts/check.py readme`` gate.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
README = REPO_ROOT / "README.md"
_BLOCK_TIMEOUT_S = 300


def _load_check_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fae_check_script", REPO_ROOT / "scripts/check.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = _load_check_script()
README_BLOCKS: list[tuple[int, str]] = CHECK.readme_python_blocks(
    README.read_text(encoding="utf-8")
)


def test_readme_has_python_examples() -> None:
    assert README_BLOCKS, "README.md must contain at least one ```python example"


@pytest.mark.parametrize(
    ("line", "source"), README_BLOCKS, ids=[f"README.md:{line}" for line, _ in README_BLOCKS]
)
def test_readme_python_block_imports_resolve(line: int, source: str) -> None:
    assert CHECK.unresolved_package_imports(source, f"README.md:{line}") == []


@pytest.mark.parametrize(
    ("line", "source"), README_BLOCKS, ids=[f"README.md:{line}" for line, _ in README_BLOCKS]
)
def test_readme_python_block_executes(line: int, source: str, tmp_path: Path) -> None:
    """Run the block in a fresh interpreter from an empty temp cwd (no repo-relative paths)."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    res = subprocess.run(  # noqa: S603
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_BLOCK_TIMEOUT_S,
    )
    assert res.returncode == 0, f"README.md:{line} failed:\n{res.stdout}\n{res.stderr}"


def test_readme_extractor_finds_only_python_fences() -> None:
    text = "# T\n\n```bash\nls\n```\n\n```python\nx = 1\n```\n\n```pythonconsole\n>>> 1\n```\n"
    assert CHECK.readme_python_blocks(text) == [(7, "x = 1\n")]


def test_unresolved_imports_reports_missing_package_names() -> None:
    source = (
        "import os\n"
        "from flight_agent_evaluator.contracts.tools import ToolCall, NoSuchName\n"
        "import flight_agent_evaluator.no_such_module\n"
    )
    assert CHECK.unresolved_package_imports(source) == [
        "flight_agent_evaluator.contracts.tools.NoSuchName",
        "flight_agent_evaluator.no_such_module",
    ]


def test_unresolved_imports_rejects_uncompilable_block() -> None:
    with pytest.raises(SyntaxError):
        CHECK.unresolved_package_imports("def broken(:\n")

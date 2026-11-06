"""Regression tests for benchmark output / provenance hardening (security findings C3, C4, C5)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine
from flight_agent_evaluator.benchmarks.manifest import BenchmarkScenarioEntry
from flight_agent_evaluator.benchmarks.results import (
    PACKAGE_REPO_ROOT,
    BenchmarkAgentExecutionProvenance,
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
    BenchmarkRunArtifact,
    semantic_sources_clean,
)


def _artifact(scenario_id: str = "sc1") -> BenchmarkRunArtifact:
    case = BenchmarkCaseResult(
        benchmark_id="bm1",
        benchmark_version="1.0.0",
        scenario_id=scenario_id,
        scenario_version=1,
        scenario_resource_digest="a" * 64,
        expectation_resource_digest="b" * 64,
        agent_id="scripted-oracle",
        task_success=True,
        safety_pass=True,
        overall_score=1.0,
        run_id="run-1",
    )
    return BenchmarkRunArtifact(
        run_semantic_id="run_sem_1",
        benchmark_id="benchmark-v1",
        benchmark_version="1.0.0",
        executed_agents=["scripted-oracle"],
        agent_provenance=[
            BenchmarkAgentExecutionProvenance(
                agent_id="scripted-oracle", agent_version="1.0.0", implementation="test"
            )
        ],
        manifest_digest="1" * 64,
        package_version="0.2.0",
        generation_command="flight-evaluator benchmark run",
        source_tree_digest=None,
        scenario_count=1,
        total_runs=1,
        metrics=BenchmarkAggregateMetrics(
            total_cases=1,
            total_runs=1,
            task_success_rate=1.0,
            safety_pass_rate=1.0,
            evaluator_error_rate=0.0,
            average_overall_score=1.0,
        ),
        case_results=[case],
    )


# ---------------------------------------------------------------------------
# C3 — path traversal through scenario ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["../evil", "a/b", "..", ".hidden", "a\\b", ""])
def test_c3_manifest_rejects_scenario_ids_that_are_not_file_name_safe(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        BenchmarkScenarioEntry(
            scenario_id=bad_id,
            scenario_path="resources/scenarios/x.json",
            scenario_sha256="a" * 64,
            expectation_path="resources/expectations/x.json",
            expectation_sha256="b" * 64,
        )


def test_c3_case_file_outside_cases_dir_is_refused(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    with pytest.raises(ValueError, match="outside the bundle's cases directory"):
        _artifact("../../escaped").persist_verified_bundle(out_dir)
    assert not any(tmp_path.rglob("*escaped*"))
    assert not (out_dir / "run.json").exists()


# ---------------------------------------------------------------------------
# C5 — --output must not clobber unrelated directories; temp files are unique
# ---------------------------------------------------------------------------


def test_c5_refuses_non_empty_non_benchmark_directory(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("my notes", encoding="utf-8")
    with pytest.raises(FileExistsError, match="no run.json"):
        _artifact().persist_verified_bundle(tmp_path)
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "my notes"
    assert not (tmp_path / "run.json").exists()


def test_c5_force_and_existing_bundle_are_allowed_without_temp_leftovers(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    _artifact().persist_verified_bundle(tmp_path, force=True)
    assert (tmp_path / "run.json").is_file()
    # A directory that already holds a benchmark bundle may be refreshed.
    _artifact().persist_verified_bundle(tmp_path)
    assert not list(tmp_path.rglob("*.tmp"))


def test_persist_verified_bundle_refuses_secrets(tmp_path: Path) -> None:
    art = _artifact()
    case = art.case_results[0].model_copy(
        update={"public_task": "Secret sk-12345678901234567890abcdef"}
    )
    art_with_secret = art.model_copy(update={"case_results": [case]})
    out_dir = tmp_path / "secret_out"
    with pytest.raises(ValueError, match="unredacted secrets"):
        art_with_secret.persist_verified_bundle(out_dir)
    assert not out_dir.exists()

    # Normal bundle writes successfully
    normal_out = tmp_path / "normal_out"
    art.persist_verified_bundle(normal_out)
    assert (normal_out / "run.json").is_file()


def test_c5_engine_refuses_before_running_any_case(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")

    class _ExplodingRunner:
        async def run_case(self, **_: Any) -> Any:
            raise AssertionError("no case may run before the output directory is accepted")

    engine = CanonicalBenchmarkEngine(runner=_ExplodingRunner())  # type: ignore[arg-type]
    with pytest.raises(FileExistsError):
        engine.run_benchmark(
            manifest_path="resources/benchmarks/benchmark-v1.json",
            agent_ids=["scripted-oracle"],
            scenario_filter=["lax-sfo-ontime"],
            output_dir=tmp_path,
        )
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "keep"


# ---------------------------------------------------------------------------
# C4 — git is not run from the cwd, without fsmonitor, and only for releases
# ---------------------------------------------------------------------------


def test_c4_ordinary_benchmark_run_never_invokes_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_subprocess(*_: Any, **__: Any) -> Any:
        raise AssertionError("git must not run for a non-release benchmark run")

    monkeypatch.setattr(subprocess, "run", _no_subprocess)
    artifact = CanonicalBenchmarkEngine().run_benchmark(
        manifest_path="resources/benchmarks/benchmark-v1.json",
        agent_ids=["scripted-oracle"],
        scenario_filter=["lax-sfo-ontime"],
    )
    assert artifact.source_tree_digest is None
    assert artifact.source_commit_sha is None


def test_c4_git_targets_package_root_with_fsmonitor_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[list[str]] = []

    def _record(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", _record)
    semantic_sources_clean()

    assert seen
    cmd = seen[0]
    assert Path(cmd[0]).is_absolute()
    assert cmd[1:3] == ["-c", "core.fsmonitor=false"]
    assert cmd[3:5] == ["-C", str(PACKAGE_REPO_ROOT)]


def test_c4_repository_fsmonitor_hook_is_not_executed(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    repo.mkdir()
    marker = tmp_path / "fsmonitor-ran"
    hook = repo / "hook.sh"
    hook.write_text(f'#!/bin/sh\necho ran > "{marker.as_posix()}"\nexit 1\n', encoding="utf-8")
    hook.chmod(0o755)
    subprocess.run([git, "init", "-q"], cwd=repo, check=True, capture_output=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [git, "config", "core.fsmonitor", hook.as_posix()],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run([git, "status", "--porcelain"], cwd=repo, capture_output=True)  # noqa: S603
    if not marker.exists():
        pytest.skip("this platform's git does not execute fsmonitor hook scripts")
    marker.unlink()

    semantic_sources_clean(repo)

    assert not marker.exists()

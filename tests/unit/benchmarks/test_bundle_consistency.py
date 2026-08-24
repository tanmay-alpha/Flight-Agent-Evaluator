"""Unit tests for ResultBundleConsistencyVerifier and validate_benchmark_bundle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from flight_agent_evaluator.benchmarks.consistency import (
    BenchmarkConsistencyError,
    ResultBundleConsistencyVerifier,
    validate_benchmark_bundle,
)


def test_canonical_benchmark_v1_bundle_passes() -> None:
    """Verify that the committed Benchmark V1 bundle passes all consistency checks."""
    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(
        "results/benchmark-v1",
        manifest_id_or_path="resources/benchmarks/benchmark-v1.json",
    )
    assert report.valid is True
    assert report.total_checks >= 9
    assert report.failed_checks == 0

    # validate_benchmark_bundle helper does not raise
    validate_benchmark_bundle(
        "results/benchmark-v1",
        manifest_id_or_path="resources/benchmarks/benchmark-v1.json",
    )


def test_missing_run_json_fails(tmp_path: Path) -> None:
    """Verify missing run.json fails closed."""
    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(tmp_path)
    assert report.valid is False
    check_ids = [c.check_id for c in report.checks if not c.passed]
    assert "BND-01-FILE-EXISTENCE" in check_ids

    with pytest.raises(BenchmarkConsistencyError, match="consistency failed"):
        validate_benchmark_bundle(tmp_path)


def test_missing_summary_json_fails(tmp_path: Path) -> None:
    """Verify missing summary.json fails closed."""
    src = Path("results/benchmark-v1")
    (tmp_path / "cases").mkdir()
    (tmp_path / "run.json").write_text(
        (src / "run.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        (src / "README.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(tmp_path)
    assert report.valid is False
    check_ids = [c.check_id for c in report.checks if not c.passed]
    assert "BND-01-FILE-EXISTENCE" in check_ids


def test_missing_readme_fails(tmp_path: Path) -> None:
    """Verify missing README.md fails closed."""
    src = Path("results/benchmark-v1")
    (tmp_path / "cases").mkdir()
    (tmp_path / "run.json").write_text(
        (src / "run.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "summary.json").write_text(
        (src / "summary.json").read_text(encoding="utf-8"), encoding="utf-8"
    )

    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(tmp_path)
    assert report.valid is False
    check_ids = [c.check_id for c in report.checks if not c.passed]
    assert "BND-01-FILE-EXISTENCE" in check_ids


def test_summary_run_metrics_divergence_fails(tmp_path: Path) -> None:
    """Verify divergence between summary.json and run.json metrics fails."""
    src = Path("results/benchmark-v1")
    (tmp_path / "cases").mkdir()
    (tmp_path / "run.json").write_text(
        (src / "run.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        (src / "README.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Mutate summary.json
    summary = json.loads((src / "summary.json").read_text(encoding="utf-8"))
    summary["task_success_rate"] = 0.999
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(
        tmp_path, manifest_id_or_path="resources/benchmarks/benchmark-v1.json"
    )
    assert report.valid is False
    check_ids = [c.check_id for c in report.checks if not c.passed]
    assert "BND-05-SUMMARY-JSON-PARITY" in check_ids


def test_readme_divergence_fails(tmp_path: Path) -> None:
    """Verify divergence between generated report and committed README fails."""
    src = Path("results/benchmark-v1")
    (tmp_path / "cases").mkdir()
    (tmp_path / "run.json").write_text(
        (src / "run.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "summary.json").write_text(
        (src / "summary.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# Stale Report\nFake content\n", encoding="utf-8")

    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(
        tmp_path, manifest_id_or_path="resources/benchmarks/benchmark-v1.json"
    )
    assert report.valid is False
    check_ids = [c.check_id for c in report.checks if not c.passed]
    assert "BND-07-README-DETERMINISTIC-PARITY" in check_ids


def test_null_journal_digest_in_case_fails(tmp_path: Path) -> None:
    """Verify null journal_digest in any case fails verification."""
    src = Path("results/benchmark-v1")
    (tmp_path / "cases").mkdir()
    raw_run = json.loads((src / "run.json").read_text(encoding="utf-8"))
    raw_run["case_results"][0]["journal_digest"] = None
    (tmp_path / "run.json").write_text(json.dumps(raw_run), encoding="utf-8")
    (tmp_path / "summary.json").write_text(
        (src / "summary.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        (src / "README.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(
        tmp_path, manifest_id_or_path="resources/benchmarks/benchmark-v1.json"
    )
    assert report.valid is False
    check_ids = [c.check_id for c in report.checks if not c.passed]
    assert "BND-06-CASE-RESULT-INTEGRITY" in check_ids


def test_tampered_disk_case_fails_bundle_verification(tmp_path: Path) -> None:
    """A physical case artifact must be identical to its embedded run.json result."""
    shutil.copytree("results/benchmark-v1", tmp_path / "bundle")
    case_file = next((tmp_path / "bundle" / "cases").glob("*.json"))
    case = json.loads(case_file.read_text(encoding="utf-8"))
    case["task_success"] = not case["task_success"]
    case_file.write_text(json.dumps(case), encoding="utf-8")

    report = ResultBundleConsistencyVerifier().verify_bundle(
        tmp_path / "bundle", manifest_id_or_path="resources/benchmarks/benchmark-v1.json"
    )

    assert report.valid is False
    assert "BND-09-DISK-CASE-SEMANTIC-PARITY" in [
        check.check_id for check in report.checks if not check.passed
    ]

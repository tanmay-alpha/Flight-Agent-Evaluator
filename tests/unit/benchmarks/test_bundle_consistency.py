"""Unit tests for ResultBundleConsistencyVerifier and validate_benchmark_bundle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from flight_agent_evaluator.benchmarks import results as benchmark_results
from flight_agent_evaluator.benchmarks.consistency import (
    BenchmarkConsistencyError,
    ResultBundleConsistencyVerifier,
    validate_benchmark_bundle,
)
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkCaseResult,
    BenchmarkExecutionIdentity,
)

_MANIFEST = "resources/benchmarks/benchmark-v1.json"


def _copied_matching_case_bundle(
    tmp_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any], Path]:
    """Return a copied bundle plus one embedded case and its physical projection."""
    bundle = tmp_path / "bundle"
    shutil.copytree("results/benchmark-v1", bundle)
    run_file = bundle / "run.json"
    raw_run: dict[str, Any] = json.loads(run_file.read_text(encoding="utf-8"))
    embedded = raw_run["case_results"][0]
    disk_file = (
        bundle
        / "cases"
        / (
            f"{embedded['scenario_id']}__{embedded['agent_id']}__rep"
            f"{embedded['repetition_index']}.json"
        )
    )
    disk: dict[str, Any] = json.loads(disk_file.read_text(encoding="utf-8"))
    assert disk == embedded
    return bundle, raw_run, disk, disk_file


def _write_case_pair(
    bundle: Path,
    raw_run: dict[str, Any],
    disk: dict[str, Any],
    disk_file: Path,
) -> None:
    (bundle / "run.json").write_text(json.dumps(raw_run), encoding="utf-8")
    disk_file.write_text(json.dumps(disk), encoding="utf-8")


def _failed_ids(report: object) -> set[str]:
    return {check.check_id for check in report.checks if not check.passed}  # type: ignore[attr-defined]


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


def test_tampered_run_semantic_id_fails_even_when_readme_is_regenerated(tmp_path: Path) -> None:
    """README parity cannot substitute for independent semantic-ID recomputation."""
    from flight_agent_evaluator.benchmarks.results import (
        BenchmarkRunArtifact,
        render_benchmark_report,
    )

    shutil.copytree("results/benchmark-v1", tmp_path / "bundle")
    run_file = tmp_path / "bundle" / "run.json"
    artifact = BenchmarkRunArtifact.model_validate_json(run_file.read_text(encoding="utf-8"))
    forged = artifact.model_copy(update={"run_semantic_id": "bm_run_forged"})
    run_file.write_text(forged.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "bundle" / "README.md").write_text(
        render_benchmark_report(forged), encoding="utf-8"
    )

    report = ResultBundleConsistencyVerifier().verify_bundle(
        tmp_path / "bundle", manifest_id_or_path="resources/benchmarks/benchmark-v1.json"
    )

    assert report.valid is False
    assert "BND-10-RUN-SEMANTIC-ID" in [
        check.check_id for check in report.checks if not check.passed
    ]


def test_duplicate_execution_run_id_fails_bundle_verification(tmp_path: Path) -> None:
    """Every materialized execution must retain its distinct deterministic run ID."""
    shutil.copytree("results/benchmark-v1", tmp_path / "bundle")
    run_file = tmp_path / "bundle" / "run.json"
    raw_run = json.loads(run_file.read_text(encoding="utf-8"))
    raw_run["case_results"][1]["run_id"] = raw_run["case_results"][0]["run_id"]
    run_file.write_text(json.dumps(raw_run), encoding="utf-8")

    report = ResultBundleConsistencyVerifier().verify_bundle(
        tmp_path / "bundle", manifest_id_or_path="resources/benchmarks/benchmark-v1.json"
    )

    assert report.valid is False
    assert "BND-13-EXECUTION-RUN-ID-UNIQUENESS" in [
        check.check_id for check in report.checks if not check.passed
    ]


def test_package_version_mismatch_fails_even_when_readme_is_regenerated(tmp_path: Path) -> None:
    """Artifact package provenance must match the installed evaluator distribution."""
    from flight_agent_evaluator.benchmarks.results import (
        BenchmarkRunArtifact,
        render_benchmark_report,
    )

    shutil.copytree("results/benchmark-v1", tmp_path / "bundle")
    run_file = tmp_path / "bundle" / "run.json"
    artifact = BenchmarkRunArtifact.model_validate_json(run_file.read_text(encoding="utf-8"))
    forged = artifact.model_copy(update={"package_version": "0.0.0-forged"})
    run_file.write_text(forged.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "bundle" / "README.md").write_text(
        render_benchmark_report(forged), encoding="utf-8"
    )

    report = ResultBundleConsistencyVerifier().verify_bundle(
        tmp_path / "bundle", manifest_id_or_path="resources/benchmarks/benchmark-v1.json"
    )

    assert report.valid is False
    assert "BND-14-PACKAGE-VERSION" in [
        check.check_id for check in report.checks if not check.passed
    ]


def test_unique_forged_run_id_fails_execution_identity(tmp_path: Path) -> None:
    """A fresh, unique run ID cannot be substituted for an expected execution ID."""
    bundle, raw_run, disk, disk_file = _copied_matching_case_bundle(tmp_path)
    embedded = raw_run["case_results"][0]
    forged_id = "12345678-1234-5678-9234-567812345678"
    embedded["run_id"] = forged_id
    disk["run_id"] = forged_id
    _write_case_pair(bundle, raw_run, disk, disk_file)

    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, _MANIFEST)

    assert report.valid is False
    assert "BND-15-EXECUTION-IDENTITY" in _failed_ids(report)


def test_rehashed_forged_run_id_still_fails_execution_identity(tmp_path: Path) -> None:
    """Independent identity validation rejects a rehashed forged execution ID."""
    bundle, raw_run, disk, disk_file = _copied_matching_case_bundle(tmp_path)
    embedded = raw_run["case_results"][0]
    forged_id = "12345678-1234-5678-9234-567812345678"
    embedded["run_id"] = forged_id
    disk["run_id"] = forged_id
    forged = BenchmarkCaseResult.model_validate(embedded)
    forged_digest = forged.compute_semantic_result_digest()
    embedded["semantic_result_digest"] = forged_digest
    disk["semantic_result_digest"] = forged_digest
    _write_case_pair(bundle, raw_run, disk, disk_file)

    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, _MANIFEST)

    assert report.valid is False
    assert "BND-15-EXECUTION-IDENTITY" in _failed_ids(report)


def test_case_digest_binds_run_id_and_declares_its_version(tmp_path: Path) -> None:
    """Changing the execution identity changes a versioned semantic result digest."""
    bundle, raw_run, _disk, _disk_file = _copied_matching_case_bundle(tmp_path)
    original = BenchmarkCaseResult.model_validate(raw_run["case_results"][0])
    changed_run_id = original.model_copy(update={"run_id": "00000000-0000-5000-8000-000000000001"})
    changed_agent = original.model_copy(update={"agent_id": "substituted-agent"})
    changed_seed = original.model_copy(update={"seed": original.seed + 1})
    changed_journal = original.model_copy(update={"journal_digest": "0" * 64})
    changed_wall_time = original.model_copy(update={"wall_time_ms": 999.0})

    assert benchmark_results.CASE_RESULT_DIGEST_VERSION == "benchmark-case-result-v2"
    assert (
        changed_run_id.compute_semantic_result_digest() != original.compute_semantic_result_digest()
    )
    assert (
        changed_agent.compute_semantic_result_digest() != original.compute_semantic_result_digest()
    )
    assert (
        changed_seed.compute_semantic_result_digest() != original.compute_semantic_result_digest()
    )
    assert (
        changed_journal.compute_semantic_result_digest()
        != original.compute_semantic_result_digest()
    )
    assert (
        changed_wall_time.compute_semantic_result_digest()
        == original.compute_semantic_result_digest()
    )
    assert bundle.is_dir()


def test_valid_looking_wrong_seed_fails_execution_domain(tmp_path: Path) -> None:
    """A deterministic ID cannot authorize a seed omitted by the declared run policy."""
    bundle, raw_run, disk, disk_file = _copied_matching_case_bundle(tmp_path)
    embedded = raw_run["case_results"][0]
    changed_seed = 43
    replacement_id = BenchmarkExecutionIdentity(
        benchmark_id=embedded["benchmark_id"],
        benchmark_version=embedded["benchmark_version"],
        manifest_digest=embedded["manifest_digest"],
        scenario_id=embedded["scenario_id"],
        scenario_version=embedded["scenario_version"],
        scenario_resource_digest=embedded["scenario_resource_digest"],
        expectation_resource_digest=embedded["expectation_resource_digest"],
        agent_id=embedded["agent_id"],
        agent_version=embedded["agent_version"],
        agent_configuration_digest=embedded["agent_configuration_digest"],
        execution_seed=changed_seed,
        repetition_index=embedded["repetition_index"],
    ).deterministic_run_id()
    embedded["seed"] = disk["seed"] = changed_seed
    embedded["run_id"] = disk["run_id"] = replacement_id
    replacement_digest = BenchmarkCaseResult.model_validate(
        embedded
    ).compute_semantic_result_digest()
    embedded["semantic_result_digest"] = disk["semantic_result_digest"] = replacement_digest
    _write_case_pair(bundle, raw_run, disk, disk_file)

    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, _MANIFEST)

    assert report.valid is False
    assert "BND-16-CASE-EXECUTION-DOMAIN" in _failed_ids(report)


def test_valid_looking_wrong_repetition_fails_execution_domain(tmp_path: Path) -> None:
    """A deterministic ID cannot authorize an undeclared repetition coordinate."""
    bundle, raw_run, disk, disk_file = _copied_matching_case_bundle(tmp_path)
    embedded = raw_run["case_results"][0]
    changed_repetition = 1
    replacement_id = BenchmarkExecutionIdentity(
        benchmark_id=embedded["benchmark_id"],
        benchmark_version=embedded["benchmark_version"],
        manifest_digest=embedded["manifest_digest"],
        scenario_id=embedded["scenario_id"],
        scenario_version=embedded["scenario_version"],
        scenario_resource_digest=embedded["scenario_resource_digest"],
        expectation_resource_digest=embedded["expectation_resource_digest"],
        agent_id=embedded["agent_id"],
        agent_version=embedded["agent_version"],
        agent_configuration_digest=embedded["agent_configuration_digest"],
        execution_seed=embedded["seed"],
        repetition_index=changed_repetition,
    ).deterministic_run_id()
    embedded["repetition_index"] = disk["repetition_index"] = changed_repetition
    embedded["run_id"] = disk["run_id"] = replacement_id
    replacement_digest = BenchmarkCaseResult.model_validate(
        embedded
    ).compute_semantic_result_digest()
    embedded["semantic_result_digest"] = disk["semantic_result_digest"] = replacement_digest
    _write_case_pair(bundle, raw_run, disk, disk_file)

    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, _MANIFEST)

    assert report.valid is False
    assert "BND-16-CASE-EXECUTION-DOMAIN" in _failed_ids(report)


def test_missing_valid_case_fails_exact_execution_matrix(tmp_path: Path) -> None:
    """The verifier requires every declared scenario-agent-seed-repetition coordinate."""
    bundle, raw_run, _disk, disk_file = _copied_matching_case_bundle(tmp_path)
    raw_run["case_results"].pop(0)
    disk_file.unlink()
    _write_case_pair(bundle, raw_run, {}, disk_file)

    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, _MANIFEST)

    assert report.valid is False
    assert "BND-17-EXECUTION-MATRIX" in _failed_ids(report)


def test_extra_valid_case_fails_exact_execution_matrix(tmp_path: Path) -> None:
    """A duplicated otherwise-valid case cannot expand the declared matrix."""
    bundle, raw_run, _disk, _disk_file = _copied_matching_case_bundle(tmp_path)
    raw_run["case_results"].append(raw_run["case_results"][0].copy())
    (bundle / "run.json").write_text(json.dumps(raw_run), encoding="utf-8")

    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, _MANIFEST)

    assert report.valid is False
    assert "BND-17-EXECUTION-MATRIX" in _failed_ids(report)


def test_stale_source_commit_fails_source_commit_provenance(tmp_path: Path) -> None:
    """A rendered README cannot make an unknown source commit authoritative."""
    from flight_agent_evaluator.benchmarks.results import (
        BenchmarkRunArtifact,
        render_benchmark_report,
    )

    bundle = tmp_path / "bundle"
    shutil.copytree("results/benchmark-v1", bundle)
    run_file = bundle / "run.json"
    artifact = BenchmarkRunArtifact.model_validate_json(run_file.read_text(encoding="utf-8"))
    forged = artifact.model_copy(update={"source_commit_sha": "0" * 40})
    run_file.write_text(forged.model_dump_json(indent=2), encoding="utf-8")
    (bundle / "README.md").write_text(render_benchmark_report(forged), encoding="utf-8")

    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, _MANIFEST)

    assert report.valid is False
    assert "BND-18-SOURCE-COMMIT-PROVENANCE" in _failed_ids(report)

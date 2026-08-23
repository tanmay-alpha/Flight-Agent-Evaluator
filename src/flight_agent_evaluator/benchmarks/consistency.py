"""Authoritative verification of benchmark result bundles, cross-file consistency, and README parity."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
)
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAggregateMetrics,
    BenchmarkRunArtifact,
    render_benchmark_report,
)


class BenchmarkConsistencyError(BenchmarkIntegrityError):
    """Raised when a benchmark result bundle is internally inconsistent, stale, or tampered with."""


@dataclass
class BundleCheckItem:
    """Individual result bundle verification check result."""

    check_id: str
    description: str
    passed: bool
    details: str = ""


@dataclass
class BundleConsistencyReport:
    """Comprehensive report detailing result bundle consistency verification."""

    valid: bool
    output_dir: str
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    checks: list[BundleCheckItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "output_dir": self.output_dir,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "checks": [
                {
                    "check_id": c.check_id,
                    "description": c.description,
                    "passed": c.passed,
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


class ResultBundleConsistencyVerifier:
    """Validates that run.json, summary.json, README.md, cases/*.json, and manifest represent the SAME execution."""

    def __init__(self, loader: BenchmarkManifestLoader | None = None) -> None:
        self.loader = loader or BenchmarkManifestLoader()

    def verify_bundle(
        self,
        output_dir: Path | str,
        manifest_id_or_path: str = "builtin:benchmark-v1",
    ) -> BundleConsistencyReport:
        """Verify internal consistency and provenance of a benchmark result bundle."""
        out_path = Path(output_dir)
        checks: list[BundleCheckItem] = []

        # 1. Existence of core result files
        run_file = out_path / "run.json"
        summary_file = out_path / "summary.json"
        readme_file = out_path / "README.md"
        cases_dir = out_path / "cases"

        files_exist = (
            run_file.is_file()
            and summary_file.is_file()
            and readme_file.is_file()
            and cases_dir.is_dir()
        )
        checks.append(
            BundleCheckItem(
                check_id="BND-01-FILE-EXISTENCE",
                description="Presence of run.json, summary.json, README.md, and cases/",
                passed=files_exist,
                details=f"Directory: {out_path}",
            )
        )

        if not files_exist:
            return BundleConsistencyReport(
                valid=False,
                output_dir=str(out_path),
                total_checks=len(checks),
                passed_checks=sum(1 for c in checks if c.passed),
                failed_checks=sum(1 for c in checks if not c.passed),
                checks=checks,
            )

        # 2. Parse artifacts
        run_artifact: BenchmarkRunArtifact | None = None
        summary_metrics: BenchmarkAggregateMetrics | None = None
        try:
            run_artifact = BenchmarkRunArtifact.model_validate_json(
                run_file.read_text(encoding="utf-8")
            )
            summary_metrics = BenchmarkAggregateMetrics.model_validate_json(
                summary_file.read_text(encoding="utf-8")
            )
            readme_text = readme_file.read_text(encoding="utf-8")
            parse_ok = True
            parse_details = f"Loaded run {run_artifact.run_semantic_id} with {len(run_artifact.case_results)} cases"
        except Exception as exc:
            parse_ok = False
            parse_details = f"Failed to parse result artifacts: {exc}"
            run_artifact = None
            summary_metrics = None
            readme_text = ""

        checks.append(
            BundleCheckItem(
                check_id="BND-02-SCHEMA-VALIDATION",
                description="Valid JSON schema for run.json and summary.json",
                passed=parse_ok,
                details=parse_details,
            )
        )

        if not parse_ok or run_artifact is None or summary_metrics is None:
            return BundleConsistencyReport(
                valid=False,
                output_dir=str(out_path),
                total_checks=len(checks),
                passed_checks=sum(1 for c in checks if c.passed),
                failed_checks=sum(1 for c in checks if not c.passed),
                checks=checks,
            )

        # 3. Manifest parity
        try:
            manifest, _ = self.loader.load_manifest(manifest_id_or_path, verify_resources=False)
            computed_m_digest = manifest.manifest_digest or manifest.compute_canonical_digest()
            manifest_match = (
                run_artifact.manifest_digest.lower() == computed_m_digest.lower()
                and run_artifact.benchmark_id == manifest.benchmark_id
                and run_artifact.benchmark_version == manifest.benchmark_version
            )
            checks.append(
                BundleCheckItem(
                    check_id="BND-03-MANIFEST-DIGEST-MATCH",
                    description="Run manifest digest matches authoritative manifest",
                    passed=manifest_match,
                    details=f"Run digest: {run_artifact.manifest_digest}, Manifest: {computed_m_digest}",
                )
            )
        except Exception as exc:
            checks.append(
                BundleCheckItem(
                    check_id="BND-03-MANIFEST-DIGEST-MATCH",
                    description="Run manifest digest matches authoritative manifest",
                    passed=False,
                    details=f"Manifest load error: {exc}",
                )
            )

        # 4. Recompute aggregate metrics from case_results
        cases = run_artifact.case_results
        total_runs = len(cases)
        if total_runs > 0:
            task_success_count = sum(1 for r in cases if r.task_success)
            safety_pass_count = sum(1 for r in cases if r.safety_pass)
            error_count = sum(
                1
                for r in cases
                if "evaluator_error" in r.failure_codes or r.evaluator_status == "evaluator_error"
            )
            avg_score = sum(r.overall_score for r in cases) / total_runs

            recomputed_task_rate = task_success_count / total_runs
            recomputed_safety_rate = safety_pass_count / total_runs
            recomputed_error_rate = error_count / total_runs
        else:
            recomputed_task_rate = 0.0
            recomputed_safety_rate = 0.0
            recomputed_error_rate = 0.0
            avg_score = 0.0

        agent_pass_rates: dict[str, float] = {}
        agent_avg_scores: dict[str, float] = {}
        for aid in run_artifact.executed_agents:
            a_results = [r for r in cases if r.agent_id == aid]
            if a_results:
                agent_pass_rates[aid] = sum(1 for r in a_results if r.task_success) / len(a_results)
                agent_avg_scores[aid] = sum(r.overall_score for r in a_results) / len(a_results)
            else:
                agent_pass_rates[aid] = 0.0
                agent_avg_scores[aid] = 0.0

        recomputed_metrics = BenchmarkAggregateMetrics(
            total_cases=run_artifact.scenario_count,
            total_runs=total_runs,
            task_success_rate=recomputed_task_rate,
            safety_pass_rate=recomputed_safety_rate,
            evaluator_error_rate=recomputed_error_rate,
            average_overall_score=avg_score,
            agent_pass_rates=agent_pass_rates,
            agent_average_scores=agent_avg_scores,
        )

        metrics_match_run = (
            recomputed_metrics.total_runs == run_artifact.metrics.total_runs
            and abs(recomputed_metrics.task_success_rate - run_artifact.metrics.task_success_rate)
            < 1e-6
            and abs(recomputed_metrics.safety_pass_rate - run_artifact.metrics.safety_pass_rate)
            < 1e-6
            and abs(
                recomputed_metrics.average_overall_score
                - run_artifact.metrics.average_overall_score
            )
            < 1e-6
            and abs(
                recomputed_metrics.evaluator_error_rate - run_artifact.metrics.evaluator_error_rate
            )
            < 1e-6
        )
        checks.append(
            BundleCheckItem(
                check_id="BND-04-RUN-METRICS-RECOMPUTATION",
                description="run.json aggregate metrics recomputed exactly from case_results",
                passed=metrics_match_run,
                details=f"Success rate: {run_artifact.metrics.task_success_rate:.4f}, avg score: {run_artifact.metrics.average_overall_score:.4f}",
            )
        )

        # 5. summary.json matches recomputed metrics
        summary_match = (
            summary_metrics.total_runs == recomputed_metrics.total_runs
            and abs(summary_metrics.task_success_rate - recomputed_metrics.task_success_rate) < 1e-6
            and abs(summary_metrics.safety_pass_rate - recomputed_metrics.safety_pass_rate) < 1e-6
            and abs(
                summary_metrics.average_overall_score - recomputed_metrics.average_overall_score
            )
            < 1e-6
            and abs(summary_metrics.evaluator_error_rate - recomputed_metrics.evaluator_error_rate)
            < 1e-6
        )
        checks.append(
            BundleCheckItem(
                check_id="BND-05-SUMMARY-JSON-PARITY",
                description="summary.json matches recomputed aggregate metrics",
                passed=summary_match,
                details="summary.json matches case recomputation",
            )
        )

        # 6. Case result integrity, digests, and non-null journal digests
        case_digests_ok = True
        case_digest_err = ""
        for _idx, cr in enumerate(cases):
            if cr.journal_digest is None or len(cr.journal_digest) != 64:
                case_digests_ok = False
                case_digest_err = f"Case {cr.scenario_id}__{cr.agent_id} has invalid journal_digest: {cr.journal_digest!r}"
                break
            if cr.manifest_digest != run_artifact.manifest_digest:
                case_digests_ok = False
                case_digest_err = f"Case {cr.scenario_id}__{cr.agent_id} manifest_digest '{cr.manifest_digest}' != run '{run_artifact.manifest_digest}'"
                break
            recomputed_digest = cr.compute_semantic_result_digest()
            if cr.semantic_result_digest != recomputed_digest:
                case_digests_ok = False
                case_digest_err = f"Case {cr.scenario_id}__{cr.agent_id} semantic_result_digest mismatch: declared '{cr.semantic_result_digest}', computed '{recomputed_digest}'"
                break

        checks.append(
            BundleCheckItem(
                check_id="BND-06-CASE-RESULT-INTEGRITY",
                description="Every case result has non-null 64-char journal_digest and valid semantic_result_digest",
                passed=case_digests_ok,
                details=case_digest_err
                or f"All {len(cases)} case results cryptographically verified",
            )
        )

        # 7. Deterministic Markdown README Parity
        generated_readme = render_benchmark_report(run_artifact)
        norm_committed = readme_text.strip().replace("\r\n", "\n")
        norm_generated = generated_readme.strip().replace("\r\n", "\n")
        readme_match = norm_committed == norm_generated
        checks.append(
            BundleCheckItem(
                check_id="BND-07-README-DETERMINISTIC-PARITY",
                description="Committed README.md matches deterministic renderer output exactly",
                passed=readme_match,
                details="README matches generated report"
                if readme_match
                else "Committed README differs from render_benchmark_report()",
            )
        )

        overall_valid = all(c.passed for c in checks)
        return BundleConsistencyReport(
            valid=overall_valid,
            output_dir=str(out_path),
            total_checks=len(checks),
            passed_checks=sum(1 for c in checks if c.passed),
            failed_checks=sum(1 for c in checks if not c.passed),
            checks=checks,
        )


def validate_benchmark_bundle(
    output_dir: Path | str,
    manifest_id_or_path: str = "builtin:benchmark-v1",
) -> None:
    """Convenience helper that asserts bundle consistency and raises BenchmarkConsistencyError on failure."""
    verifier = ResultBundleConsistencyVerifier()
    report = verifier.verify_bundle(output_dir, manifest_id_or_path=manifest_id_or_path)
    if not report.valid:
        failed = [c for c in report.checks if not c.passed]
        details = "; ".join(f"[{c.check_id}] {c.description}: {c.details}" for c in failed)
        raise BenchmarkConsistencyError(f"Benchmark result bundle consistency failed: {details}")

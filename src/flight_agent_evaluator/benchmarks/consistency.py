"""Authoritative verification of benchmark result bundles, cross-file consistency, and README parity."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from flight_agent_evaluator.benchmarks.engine import compute_run_semantic_id
from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
)
from flight_agent_evaluator.benchmarks.registry import BenchmarkAgentRegistry
from flight_agent_evaluator.benchmarks.results import (
    BenchmarkAggregateMetrics,
    BenchmarkCaseResult,
    BenchmarkExecutionIdentity,
    BenchmarkRunArtifact,
    compute_source_tree_digest,
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
            manifest, manifest_cases = self.loader.load_manifest(
                manifest_id_or_path, verify_resources=True
            )
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

        # Recorded agent provenance must agree with both manifest and executable registry metadata.
        try:
            manifest_agents = {agent.agent_id: agent for agent in manifest.agents}
            registry = BenchmarkAgentRegistry()
            agent_provenance_matches = all(
                provenance.agent_id in manifest_agents
                and provenance.agent_version == manifest_agents[provenance.agent_id].agent_version
                and provenance.implementation == manifest_agents[provenance.agent_id].implementation
                and provenance.configuration_digest
                == manifest_agents[provenance.agent_id].configuration_digest
                and provenance.agent_version
                == registry.get_metadata(provenance.agent_id)["agent_version"]
                and provenance.implementation
                == registry.get_metadata(provenance.agent_id)["implementation"]
                for provenance in run_artifact.agent_provenance
            ) and {provenance.agent_id for provenance in run_artifact.agent_provenance} == set(
                run_artifact.executed_agents
            )
            agent_provenance_details = "Artifact, manifest, and registry agent provenance agree."
        except Exception as exc:
            agent_provenance_matches = False
            agent_provenance_details = f"Unable to verify agent provenance: {exc}"
        checks.append(
            BundleCheckItem(
                check_id="BND-12-AGENT-PROVENANCE",
                description="Executed agent provenance matches manifest declarations and registry metadata",
                passed=agent_provenance_matches,
                details=agent_provenance_details,
            )
        )

        # Every recorded run ID must independently derive from authoritative execution inputs.
        try:
            identity_cases = {case.manifest_entry.scenario_id: case for case in manifest_cases}
            identity_registry = BenchmarkAgentRegistry()
            execution_identity_matches = True
            execution_identity_details = f"All {len(run_artifact.case_results)} run IDs match deterministic execution identities."
            for case_result in run_artifact.case_results:
                manifest_case = identity_cases.get(case_result.scenario_id)
                if manifest_case is None:
                    execution_identity_matches = False
                    execution_identity_details = (
                        f"Unknown scenario coordinate: {case_result.scenario_id!r}"
                    )
                    break
                metadata = identity_registry.get_metadata(case_result.agent_id)
                expected_run_id = BenchmarkExecutionIdentity(
                    benchmark_id=manifest.benchmark_id,
                    benchmark_version=manifest.benchmark_version,
                    manifest_digest=computed_m_digest,
                    scenario_id=manifest_case.manifest_entry.scenario_id,
                    scenario_version=manifest_case.manifest_entry.scenario_version,
                    scenario_resource_digest=manifest_case.scenario_raw_sha256,
                    expectation_resource_digest=manifest_case.expectation_raw_sha256,
                    agent_id=case_result.agent_id,
                    agent_version=metadata["agent_version"],
                    agent_configuration_digest=metadata.get("configuration_digest"),
                    execution_seed=case_result.seed,
                    repetition_index=case_result.repetition_index,
                ).deterministic_run_id()
                if case_result.run_id != expected_run_id:
                    execution_identity_matches = False
                    execution_identity_details = (
                        f"{case_result.scenario_id}__{case_result.agent_id}: "
                        f"recorded={case_result.run_id}, expected={expected_run_id}"
                    )
                    break
        except Exception as exc:
            execution_identity_matches = False
            execution_identity_details = f"Unable to reconstruct execution identity: {exc}"
        checks.append(
            BundleCheckItem(
                check_id="BND-15-EXECUTION-IDENTITY",
                description="Every case run ID equals its deterministic execution identity",
                passed=execution_identity_matches,
                details=execution_identity_details,
            )
        )

        # Case coordinates and metadata must be drawn from the declared execution policy.
        try:
            declared_case_ids = set(run_artifact.selected_scenario_ids)
            declared_cases = {
                case.manifest_entry.scenario_id: case
                for case in manifest_cases
                if case.manifest_entry.scenario_id in declared_case_ids
            }
            policy_seeds = set(run_artifact.run_policy["seeds"])
            policy_repetitions = run_artifact.run_policy["repetitions"]
            domain_registry = BenchmarkAgentRegistry()
            domain_matches = len(declared_cases) == len(declared_case_ids)
            domain_details = "All case execution coordinates are declared by the manifest, registry, and run policy."
            for case_result in run_artifact.case_results:
                declared_case = declared_cases.get(case_result.scenario_id)
                domain_metadata = (
                    domain_registry.get_metadata(case_result.agent_id)
                    if case_result.agent_id in run_artifact.executed_agents
                    else None
                )
                if (
                    declared_case is None
                    or domain_metadata is None
                    or case_result.seed not in policy_seeds
                    or not 0 <= case_result.repetition_index < policy_repetitions
                    or case_result.scenario_resource_digest != declared_case.scenario_raw_sha256
                    or case_result.expectation_resource_digest
                    != declared_case.expectation_raw_sha256
                    or case_result.agent_version != domain_metadata["agent_version"]
                    or case_result.agent_configuration_digest
                    != domain_metadata.get("configuration_digest")
                ):
                    domain_matches = False
                    domain_details = (
                        f"Undeclared execution coordinate: {case_result.scenario_id}__"
                        f"{case_result.agent_id}__seed{case_result.seed}__"
                        f"rep{case_result.repetition_index}"
                    )
                    break
        except Exception as exc:
            domain_matches = False
            domain_details = f"Unable to validate case execution domain: {exc}"
            declared_cases = {}
            policy_seeds = set()
            policy_repetitions = 0
        checks.append(
            BundleCheckItem(
                check_id="BND-16-CASE-EXECUTION-DOMAIN",
                description="Every case coordinate and provenance field is declared by the execution policy",
                passed=domain_matches,
                details=domain_details,
            )
        )

        try:
            expected_execution_keys = {
                (scenario_id, agent_id, seed, repetition_index)
                for scenario_id in declared_cases
                for agent_id in run_artifact.executed_agents
                for seed in policy_seeds
                for repetition_index in range(policy_repetitions)
            }
            actual_execution_keys = [
                (case.scenario_id, case.agent_id, case.seed, case.repetition_index)
                for case in run_artifact.case_results
            ]
            actual_execution_key_set = set(actual_execution_keys)
            matrix_matches = actual_execution_key_set == expected_execution_keys and len(
                actual_execution_keys
            ) == len(actual_execution_key_set)
            matrix_details = (
                f"missing={sorted(expected_execution_keys - actual_execution_key_set)}, "
                f"extra={sorted(actual_execution_key_set - expected_execution_keys)}, "
                f"duplicates={len(actual_execution_keys) - len(actual_execution_key_set)}"
            )
        except Exception as exc:
            matrix_matches = False
            matrix_details = f"Unable to validate execution matrix: {exc}"
        checks.append(
            BundleCheckItem(
                check_id="BND-17-EXECUTION-MATRIX",
                description="Case results equal the exact scenario-agent-seed-repetition execution matrix",
                passed=matrix_matches,
                details=matrix_details,
            )
        )

        # Recompute content-addressed selection identity independently of run.json and README.
        try:
            selected_case_ids = set(run_artifact.selected_scenario_ids)
            selected_cases = [
                case
                for case in manifest_cases
                if case.manifest_entry.scenario_id in selected_case_ids
            ]
            registry = BenchmarkAgentRegistry()
            resolved_agents = [
                (agent_id, registry.resolve(agent_id), registry.get_metadata(agent_id))
                for agent_id in run_artifact.executed_agents
            ]
            computed_run_id = compute_run_semantic_id(
                manifest_digest=run_artifact.manifest_digest,
                benchmark_id=run_artifact.benchmark_id,
                benchmark_version=run_artifact.benchmark_version,
                environment_version=run_artifact.environment_version,
                evaluator_version=run_artifact.evaluator_version,
                taxonomy_version=run_artifact.taxonomy_version,
                scoring_profile_version=run_artifact.scoring_profile_version,
                selected_scenarios=selected_cases,
                executed_agents=resolved_agents,
                run_policy=run_artifact.run_policy,
            )
            run_semantic_matches = computed_run_id == run_artifact.run_semantic_id
            run_semantic_details = (
                f"recorded={run_artifact.run_semantic_id}, computed={computed_run_id}"
            )
        except Exception as exc:
            run_semantic_matches = False
            run_semantic_details = f"Unable to recompute run semantic ID: {exc}"
        checks.append(
            BundleCheckItem(
                check_id="BND-10-RUN-SEMANTIC-ID",
                description="Run semantic ID recomputes from manifest selection, agent provenance, and policy",
                passed=run_semantic_matches,
                details=run_semantic_details,
            )
        )

        # Source-tree provenance is authoritative even when Git commit topology changes.
        try:
            computed_source_digest = compute_source_tree_digest()
            source_digest_matches = run_artifact.source_tree_digest == computed_source_digest
            source_details = (
                f"recorded={run_artifact.source_tree_digest}, computed={computed_source_digest}"
            )
        except Exception as exc:
            source_digest_matches = False
            source_details = f"Unable to compute source tree digest: {exc}"
        checks.append(
            BundleCheckItem(
                check_id="BND-11-SOURCE-TREE-DIGEST",
                description="Recorded source tree digest matches exact current semantic runtime sources",
                passed=source_digest_matches,
                details=source_details,
            )
        )

        # A source-release artifact may be followed only by evidence commits, never semantic code drift.
        if run_artifact.source_commit_sha is None:
            source_commit_matches = True
            source_commit_details = (
                "Source commit provenance is unavailable for this non-release execution."
            )
        else:
            semantic_paths = [
                "src/flight_agent_evaluator",
                "resources",
                "pyproject.toml",
                "uv.lock",
            ]
            try:
                exists = (
                    subprocess.run(  # noqa: S603, S607
                        ["git", "cat-file", "-e", f"{run_artifact.source_commit_sha}^{{commit}}"],  # noqa: S607
                        check=False,
                        capture_output=True,
                        timeout=5.0,
                    ).returncode
                    == 0
                )
                ancestor = (
                    exists
                    and subprocess.run(  # noqa: S603, S607
                        [
                            "git",  # noqa: S607
                            "merge-base",
                            "--is-ancestor",
                            run_artifact.source_commit_sha,
                            "HEAD",
                        ],  # noqa: S607
                        check=False,
                        capture_output=True,
                        timeout=5.0,
                    ).returncode
                    == 0
                )
                no_semantic_diff = (
                    ancestor
                    and subprocess.run(  # noqa: S603, S607
                        [
                            "git",  # noqa: S607
                            "diff",
                            "--quiet",
                            f"{run_artifact.source_commit_sha}..HEAD",
                            "--",
                            *semantic_paths,
                        ],  # noqa: S607
                        check=False,
                        capture_output=True,
                        timeout=5.0,
                    ).returncode
                    == 0
                )
                source_commit_matches = bool(exists and ancestor and no_semantic_diff)
                source_commit_details = (
                    f"exists={exists}, ancestor={ancestor}, semantic_diff={not no_semantic_diff}"
                )
            except (FileNotFoundError, subprocess.SubprocessError) as exc:
                source_commit_matches = False
                source_commit_details = f"Git source commit provenance unavailable: {exc}"
        checks.append(
            BundleCheckItem(
                check_id="BND-18-SOURCE-COMMIT-PROVENANCE",
                description="Source commit exists, is an ancestor, and has no later semantic-source diff",
                passed=source_commit_matches,
                details=source_commit_details,
            )
        )

        # Package provenance must be bound to the distribution executing this verifier.
        try:
            installed_package_version = version("flight-agent-evaluator")
            package_version_matches = run_artifact.package_version == installed_package_version
            package_version_details = (
                f"recorded={run_artifact.package_version}, installed={installed_package_version}"
            )
        except PackageNotFoundError:
            package_version_matches = False
            package_version_details = "The flight-agent-evaluator distribution is not installed."
        checks.append(
            BundleCheckItem(
                check_id="BND-14-PACKAGE-VERSION",
                description="Recorded package version matches the installed evaluator distribution",
                passed=package_version_matches,
                details=package_version_details,
            )
        )

        # 4. Recompute aggregate metrics from case_results
        cases = run_artifact.case_results
        execution_run_ids = [case.run_id for case in cases]
        unique_execution_ids = len(execution_run_ids) == len(set(execution_run_ids))
        checks.append(
            BundleCheckItem(
                check_id="BND-13-EXECUTION-RUN-ID-UNIQUENESS",
                description="Every materialized case execution has a unique deterministic run ID",
                passed=unique_execution_ids,
                details=(
                    f"{len(execution_run_ids)} execution IDs, {len(set(execution_run_ids))} unique"
                ),
            )
        )
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

        # 7. Physical case artifacts must be an exact, semantic projection of run.json.
        expected_cases = {
            f"{case.scenario_id}__{case.agent_id}__rep{case.repetition_index}.json": case
            for case in cases
        }
        actual_case_files = {path.name: path for path in cases_dir.glob("*.json")}
        exact_case_set = set(actual_case_files) == set(expected_cases)
        checks.append(
            BundleCheckItem(
                check_id="BND-08-DISK-CASE-EXACT-SET",
                description="cases/ contains exactly one expected JSON artifact per embedded case result",
                passed=exact_case_set,
                details=(
                    f"missing={sorted(set(expected_cases) - set(actual_case_files))}, "
                    f"extra={sorted(set(actual_case_files) - set(expected_cases))}"
                ),
            )
        )

        disk_cases_match = exact_case_set
        disk_case_details = "All physical case artifacts equal their embedded result."
        if disk_cases_match:
            for name, expected in expected_cases.items():
                try:
                    actual = BenchmarkCaseResult.model_validate_json(
                        actual_case_files[name].read_text(encoding="utf-8")
                    )
                except Exception as exc:
                    disk_cases_match = False
                    disk_case_details = f"{name} is not a valid BenchmarkCaseResult: {exc}"
                    break
                if actual != expected:
                    disk_cases_match = False
                    disk_case_details = f"{name} differs from embedded run.json case result"
                    break
        checks.append(
            BundleCheckItem(
                check_id="BND-09-DISK-CASE-SEMANTIC-PARITY",
                description="Every physical case JSON equals its corresponding embedded run.json case result",
                passed=disk_cases_match,
                details=disk_case_details,
            )
        )

        # 10. Deterministic Markdown README Parity
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

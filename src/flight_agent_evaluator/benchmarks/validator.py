"""Corpus consistency validator and manifest generator for Benchmark V1."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
from flight_agent_evaluator.benchmarks.manifest import (
    BenchmarkAgentEntry,
    BenchmarkManifest,
    BenchmarkRunPolicy,
    BenchmarkScenarioEntry,
)

logger = logging.getLogger(__name__)


@dataclass
class CorpusValidationError:
    """Diagnostic detail for a corpus validation violation."""

    code: str
    scenario_id: str
    resource: str
    message: str


@dataclass
class CorpusValidationReport:
    """Comprehensive validation outcome for the benchmark scenario corpus."""

    benchmark_id: str
    manifest_digest: str
    valid: bool
    total_scenarios: int
    errors: list[CorpusValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "manifest_digest": self.manifest_digest,
            "valid": self.valid,
            "total_scenarios": self.total_scenarios,
            "errors": [
                {
                    "code": err.code,
                    "scenario_id": err.scenario_id,
                    "resource": err.resource,
                    "message": err.message,
                }
                for err in self.errors
            ],
            "warnings": self.warnings,
        }


class BenchmarkCorpusValidator:
    """Validates the cryptographic, structural, and semantic consistency of the benchmark corpus."""

    def __init__(self, resource_root: Path | str | None = None) -> None:
        self.resource_root = Path(resource_root) if resource_root else Path(".")
        self.loader = BenchmarkManifestLoader(resource_root=self.resource_root)

    def compute_file_sha256(self, rel_path: str) -> str:
        """Compute the raw bytes SHA-256 digest of a resource file."""
        abs_path = self.loader.resolve_secure_path(rel_path)
        return hashlib.sha256(abs_path.read_bytes()).hexdigest()

    def build_authoritative_manifest(
        self,
        benchmark_id: str = "benchmark-v1",
        benchmark_version: str = "1.0.0",
        environment_version: str = "1.0.0",
        evaluator_version: str = "1.0.0",
        taxonomy_version: str = "1.0.0",
        scoring_profile_version: str = "1.0.0",
    ) -> BenchmarkManifest:
        """Build an authoritative manifest by hashing all 24 canonical scenario-expectation pairs."""
        scenario_configs = [
            # 12 Read-only scenarios
            (
                "jfk-lhr-delay",
                "resources/scenarios/jfk-lhr-delay.json",
                "resources/expectations/jfk-lhr-delay.json",
                "read_only",
                "medium",
                ("disruption", "delay"),
            ),
            (
                "lax-sfo-ontime",
                "resources/scenarios/lax-sfo-ontime.json",
                "resources/expectations/lax-sfo-ontime.json",
                "read_only",
                "easy",
                ("ontime", "baseline"),
            ),
            (
                "atl-mia-wrong-arguments",
                "resources/scenarios/atl-mia-wrong-arguments.json",
                "resources/expectations/atl-mia-wrong-arguments.json",
                "read_only",
                "easy",
                ("validation", "arguments"),
            ),
            (
                "bwi-mco-forbidden-mutation",
                "resources/scenarios/bwi-mco-forbidden-mutation.json",
                "resources/expectations/bwi-mco-forbidden-mutation.json",
                "read_only",
                "medium",
                ("safety", "forbidden-mutation"),
            ),
            (
                "clt-phx-retry-dependency",
                "resources/scenarios/clt-phx-retry-dependency.json",
                "resources/expectations/clt-phx-retry-dependency.json",
                "read_only",
                "medium",
                ("retry", "dependency"),
            ),
            (
                "dfw-den-no-alternatives",
                "resources/scenarios/dfw-den-no-alternatives.json",
                "resources/expectations/dfw-den-no-alternatives.json",
                "read_only",
                "medium",
                ("search", "empty-results"),
            ),
            (
                "iad-ord-redundant-lookup",
                "resources/scenarios/iad-ord-redundant-lookup.json",
                "resources/expectations/iad-ord-redundant-lookup.json",
                "read_only",
                "easy",
                ("efficiency", "redundancy"),
            ),
            (
                "ord-sea-dual-order",
                "resources/scenarios/ord-sea-dual-order.json",
                "resources/expectations/ord-sea-dual-order.json",
                "read_only",
                "medium",
                ("trajectory", "ordering"),
            ),
            (
                "prompt-injection-untrusted-output",
                "resources/scenarios/prompt-injection-untrusted-output.json",
                "resources/expectations/prompt-injection-untrusted-output.json",
                "read_only",
                "hard",
                ("security", "prompt-injection"),
            ),
            (
                "sfo-bos-optional-lookup",
                "resources/scenarios/sfo-bos-optional-lookup.json",
                "resources/expectations/sfo-bos-optional-lookup.json",
                "read_only",
                "easy",
                ("optional-step",),
            ),
            (
                "unknown-flight-lookup",
                "resources/scenarios/unknown-flight-lookup.json",
                "resources/expectations/unknown-flight-lookup.json",
                "read_only",
                "easy",
                ("error-handling",),
            ),
            (
                "jfk-lhr-timeout-recovery",
                "resources/scenarios/jfk-lhr-timeout-recovery.json",
                "resources/expectations/jfk-lhr-timeout-recovery.json",
                "read_only",
                "hard",
                ("fault-injection", "timeout"),
            ),
            # 12 Transactional stage-5 scenarios
            (
                "approval-granted",
                "resources/scenarios/stage-5/approval-granted.json",
                "resources/expectations/stage-5/approval-granted.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "approval"),
            ),
            (
                "approval-denied",
                "resources/scenarios/stage-5/approval-denied.json",
                "resources/expectations/stage-5/approval-denied.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "approval-denied"),
            ),
            (
                "approval-expires",
                "resources/scenarios/stage-5/approval-expires.json",
                "resources/expectations/stage-5/approval-expires.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "approval-expires"),
            ),
            (
                "mutation-without-approval",
                "resources/scenarios/stage-5/mutation-without-approval.json",
                "resources/expectations/stage-5/mutation-without-approval.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "safety"),
            ),
            (
                "payload-changes-after-approval",
                "resources/scenarios/stage-5/payload-changes-after-approval.json",
                "resources/expectations/stage-5/payload-changes-after-approval.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "payload-hash"),
            ),
            (
                "idempotent-retry-after-timeout",
                "resources/scenarios/stage-5/idempotent-retry-after-timeout.json",
                "resources/expectations/stage-5/idempotent-retry-after-timeout.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "idempotency"),
            ),
            (
                "duplicate-rebooking-attempt",
                "resources/scenarios/stage-5/duplicate-rebooking-attempt.json",
                "resources/expectations/stage-5/duplicate-rebooking-attempt.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "duplicate-rebooking"),
            ),
            (
                "hold-expires",
                "resources/scenarios/stage-5/hold-expires.json",
                "resources/expectations/stage-5/hold-expires.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "hold-expires"),
            ),
            (
                "mutation-success-response-lost",
                "resources/scenarios/stage-5/mutation-success-response-lost.json",
                "resources/expectations/stage-5/mutation-success-response-lost.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "ambiguous-commit"),
            ),
            (
                "alternative-disappears-before-confirm",
                "resources/scenarios/stage-5/alternative-disappears-before-confirm.json",
                "resources/expectations/stage-5/alternative-disappears-before-confirm.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "inventory-loss"),
            ),
            (
                "approval-wrong-itinerary",
                "resources/scenarios/stage-5/approval-wrong-itinerary.json",
                "resources/expectations/stage-5/approval-wrong-itinerary.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "scope-mismatch"),
            ),
            (
                "constraint-changes-after-approval",
                "resources/scenarios/stage-5/constraint-changes-after-approval.json",
                "resources/expectations/stage-5/constraint-changes-after-approval.json",
                "transactional",
                "hard",
                ("stage-5", "transaction", "stale-approval"),
            ),
        ]

        entries: list[BenchmarkScenarioEntry] = []
        for sid, sc_path, exp_path, fam, diff, tags in scenario_configs:
            sc_sha = self.compute_file_sha256(sc_path)
            exp_sha = self.compute_file_sha256(exp_path)
            entry = BenchmarkScenarioEntry(
                scenario_id=sid,
                scenario_version=1,
                scenario_path=sc_path,
                scenario_sha256=sc_sha,
                expectation_path=exp_path,
                expectation_sha256=exp_sha,
                family=fam,
                difficulty=diff,
                tags=tags,
            )
            entries.append(entry)

        agents = [
            BenchmarkAgentEntry(
                agent_id="scripted-oracle",
                agent_version="1.0.0",
                implementation="flight_agent_evaluator.agent.baselines.ScriptedOracleAgent",
            ),
            BenchmarkAgentEntry(
                agent_id="naive-baseline",
                agent_version="1.0.0",
                implementation="flight_agent_evaluator.agent.baselines.NaiveBaselineAgent",
            ),
            BenchmarkAgentEntry(
                agent_id="random-baseline",
                agent_version="1.0.0",
                implementation="flight_agent_evaluator.agent.baselines.RandomBaselineAgent",
            ),
        ]

        manifest_no_digest = BenchmarkManifest(
            benchmark_id=benchmark_id,
            benchmark_version=benchmark_version,
            title="Flight Agent Evaluator Benchmark V1",
            description="Curated benchmark suite of 24 deterministic aviation scenarios spanning read-only disruption handling and Stage 5 transactional safety.",
            environment_version=environment_version,
            evaluator_version=evaluator_version,
            taxonomy_version=taxonomy_version,
            scoring_profile_version=scoring_profile_version,
            judge_validation_status="human_calibration_pending",
            scenarios=tuple(entries),
            agents=tuple(agents),
            run_policy=BenchmarkRunPolicy(repetitions=1, seeds=(42,)),
        )
        computed_digest = manifest_no_digest.compute_canonical_digest()
        return manifest_no_digest.model_copy(update={"manifest_digest": computed_digest})

    def validate_manifest_file(self, manifest_path: Path | str) -> CorpusValidationReport:
        """Validate a manifest file and all referenced scenario/expectation files."""
        errors: list[CorpusValidationError] = []
        try:
            manifest, cases = self.loader.load_manifest(manifest_path, verify_resources=True)
        except Exception as exc:
            err_code = (
                "MANIFEST_NOT_FOUND"
                if "not found" in str(exc).lower() or isinstance(exc, FileNotFoundError)
                else "MANIFEST_LOAD_FAILED"
            )
            errors.append(
                CorpusValidationError(
                    code=err_code,
                    scenario_id="",
                    resource=str(manifest_path),
                    message=str(exc),
                )
            )
            return CorpusValidationReport(
                benchmark_id="",
                manifest_digest="",
                valid=False,
                total_scenarios=0,
                errors=errors,
            )

        # Cross-validate each case
        for case in cases:
            sid = case.manifest_entry.scenario_id
            if case.scenario.scenario_id.id != sid:
                errors.append(
                    CorpusValidationError(
                        code="SCENARIO_ID_MISMATCH",
                        scenario_id=sid,
                        resource=case.manifest_entry.scenario_path,
                        message=f"Scenario ID '{case.scenario.scenario_id.id}' does not match entry '{sid}'.",
                    )
                )
            if case.expectation.scenario_id != sid:
                errors.append(
                    CorpusValidationError(
                        code="EXPECTATION_ID_MISMATCH",
                        scenario_id=sid,
                        resource=case.manifest_entry.expectation_path,
                        message=f"Expectation ID '{case.expectation.scenario_id}' does not match entry '{sid}'.",
                    )
                )

        manifest_digest = manifest.manifest_digest or manifest.compute_canonical_digest()
        return CorpusValidationReport(
            benchmark_id=manifest.benchmark_id,
            manifest_digest=manifest_digest,
            valid=len(errors) == 0,
            total_scenarios=len(cases),
            errors=errors,
        )

"""Bias probe framework for judge system validation.

Bias probes test whether the judge's scores change in response to
manipulations that should not affect the correct evaluation.

Probe types implemented:
- Position bias: does the order of observations affect scores?
- Verbosity bias: does a longer final response get scored higher?
- Style bias: does formatting (lists vs prose) affect scores?
- Evidence order bias: does observation order affect groundedness?

These probes do NOT require human labels.  They validate judge consistency
by checking that manipulations produce approximately equal scores.

All probes return a BiasProbeResult, not a verdict.  Human review is
required to interpret whether observed differences are acceptable.

Status: engineering complete; human calibration pending.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
    JudgeEvidencePackage,
    JudgeResult,
)


@dataclass
class BiasProbeResult:
    """Result of a single bias probe."""

    probe_type: str
    criterion: JudgeCriterion
    original_score: int
    manipulated_score: int
    score_delta: int = field(init=False)
    manipulated_package_id: str = ""
    notes: str = ""
    run_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self.score_delta = self.manipulated_score - self.original_score

    @property
    def is_stable(self) -> bool:
        """Return True if the score delta is zero (perfect stability)."""
        return self.score_delta == 0


@dataclass
class BiasProbeSuite:
    """Collection of bias probe results for a single evidence package."""

    original_package_id: str
    original_result: JudgeResult
    probes: list[BiasProbeResult] = field(default_factory=list)
    run_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add(self, probe: BiasProbeResult) -> None:
        self.probes.append(probe)

    @property
    def total_probes(self) -> int:
        return len(self.probes)

    @property
    def stable_probes(self) -> int:
        return sum(1 for p in self.probes if p.is_stable)

    @property
    def stability_rate(self) -> float:
        if self.total_probes == 0:
            return 1.0
        return self.stable_probes / self.total_probes

    def delta_by_type(self) -> dict[str, list[int]]:
        """Return score deltas grouped by probe type."""
        result: dict[str, list[int]] = {}
        for p in self.probes:
            result.setdefault(p.probe_type, []).append(p.score_delta)
        return result


def _reverse_observations(package: JudgeEvidencePackage) -> JudgeEvidencePackage:
    """Return a copy with observations in reversed order."""
    reversed_obs = list(reversed(package.trusted_observations))
    return JudgeEvidencePackage(
        package_id=f"{package.package_id}-reversed",
        scenario_id=package.scenario_id,
        run_id=package.run_id,
        public_task=package.public_task,
        trusted_observations=reversed_obs,
        final_response=package.final_response,
        tool_call_summary=package.tool_call_summary,
        created_at=package.created_at,
    )


def _extend_response(package: JudgeEvidencePackage) -> JudgeEvidencePackage:
    """Return a copy with a verbosely padded final response (verbosity probe)."""
    padded = (
        package.final_response
        + "\n\nAdditional detail: Please note that the above response covers all"
        " relevant aspects of your query comprehensively."
    )
    return JudgeEvidencePackage(
        package_id=f"{package.package_id}-verbose",
        scenario_id=package.scenario_id,
        run_id=package.run_id,
        public_task=package.public_task,
        trusted_observations=package.trusted_observations,
        final_response=padded,
        tool_call_summary=package.tool_call_summary,
        created_at=package.created_at,
    )


def _format_as_bullets(package: JudgeEvidencePackage) -> JudgeEvidencePackage:
    """Return a copy with final response reformatted as a bullet list (style probe)."""
    lines = package.final_response.strip().split(". ")
    bulleted = "\n".join(f"• {line.strip().rstrip('.')}." for line in lines if line.strip())
    return JudgeEvidencePackage(
        package_id=f"{package.package_id}-bullets",
        scenario_id=package.scenario_id,
        run_id=package.run_id,
        public_task=package.public_task,
        trusted_observations=package.trusted_observations,
        final_response=bulleted,
        tool_call_summary=package.tool_call_summary,
        created_at=package.created_at,
    )


def build_probe_packages(
    package: JudgeEvidencePackage,
) -> dict[str, JudgeEvidencePackage]:
    """Return a dict of probe type → manipulated package.

    Each manipulated package should be scored with the same judge client
    as the original.  Score differences indicate potential bias.
    """
    probes: dict[str, JudgeEvidencePackage] = {}
    if len(package.trusted_observations) >= 2:
        probes["evidence_order"] = _reverse_observations(package)
    probes["verbosity"] = _extend_response(package)
    probes["style_format"] = _format_as_bullets(package)
    return probes


def compute_probe_results(
    original_result: JudgeResult,
    probe_results: dict[str, JudgeResult],
) -> BiasProbeSuite:
    """Compute BiasProbeResult for each manipulated package."""
    suite = BiasProbeSuite(
        original_package_id=original_result.package_id,
        original_result=original_result,
    )
    for probe_type, manipulated in probe_results.items():
        for criterion in JudgeCriterion:
            orig_score = original_result.criterion_score(criterion)
            manip_score = manipulated.criterion_score(criterion)
            if orig_score is not None and manip_score is not None:
                suite.add(
                    BiasProbeResult(
                        probe_type=probe_type,
                        criterion=criterion,
                        original_score=orig_score,
                        manipulated_score=manip_score,
                        manipulated_package_id=manipulated.package_id,
                    )
                )
    return suite

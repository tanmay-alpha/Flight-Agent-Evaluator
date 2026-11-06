"""Deterministic comparisons of self-contained benchmark run.json bundles.

Deltas are candidate minus baseline. A passing case has task success, safety
pass, and no evaluator error. Only matched (agent, scenario, seed, repetition)
cases can become newly failing/passing; unmatched cases are reported separately.
"""

from __future__ import annotations

import json
from math import fsum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from flight_agent_evaluator.benchmarks.results import BenchmarkCaseResult, BenchmarkRunArtifact
from flight_agent_evaluator.strict_json import load_strict_path


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricDelta(_ReportModel):
    """Rates and score changes for one named agent or scenario (absolute units)."""

    name: str
    baseline_runs: int
    candidate_runs: int
    task_success_delta: float | None
    safety_pass_delta: float | None
    overall_score_delta: float | None


class CaseChange(_ReportModel):
    """A matched transition or an explicitly unmatched execution identity."""

    agent_id: str
    scenario_id: str
    seed: int
    repetition_index: int
    baseline_codes: list[str]
    candidate_codes: list[str]


class RunComparisonReport(_ReportModel):
    """Stable machine-readable and Markdown comparison, excluding wall clocks."""

    baseline_run_id: str
    candidate_run_id: str
    baseline_manifest_digest: str
    candidate_manifest_digest: str
    manifest_matches: bool
    task_success_delta: float
    safety_pass_delta: float
    overall_score_delta: float
    per_agent: list[MetricDelta]
    per_scenario: list[MetricDelta]
    newly_failing: list[CaseChange]
    newly_passing: list[CaseChange]
    added_cases: list[CaseChange]
    removed_cases: list[CaseChange]

    def render_markdown(self) -> str:
        """Render deterministic Markdown without host paths or timestamps."""

        def escape(text: str) -> str:
            return (
                text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")
            )

        def delta(value: float | None) -> str:
            return "n/a" if value is None else f"{value:+.4f}"

        lines = [
            "# Benchmark run comparison",
            "",
            f"Baseline: {escape(self.baseline_run_id)}",
            f"Candidate: {escape(self.candidate_run_id)}",
            f"Manifest match: {self.manifest_matches}",
            "",
            "Deltas are candidate minus baseline (absolute rates/scores).",
            f"Task success delta: {delta(self.task_success_delta)}",
            f"Safety pass delta: {delta(self.safety_pass_delta)}",
            f"Overall score delta: {delta(self.overall_score_delta)}",
        ]
        for title, rows in (("Per agent", self.per_agent), ("Per scenario", self.per_scenario)):
            lines.extend(
                [
                    "",
                    f"## {title}",
                    "",
                    "| Name | Baseline runs | Candidate runs | Task success Δ | Safety Δ | Score Δ |",
                    "| --- | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            lines.extend(
                f"| {escape(r.name)} | {r.baseline_runs} | {r.candidate_runs} | {delta(r.task_success_delta)} | {delta(r.safety_pass_delta)} | {delta(r.overall_score_delta)} |"
                for r in rows
            )
        for title, cases in (
            ("Newly failing", self.newly_failing),
            ("Newly passing", self.newly_passing),
            ("Added cases", self.added_cases),
            ("Removed cases", self.removed_cases),
        ):
            lines.extend(["", f"## {title}", ""])
            if not cases:
                lines.append("None.")
            for case in cases:
                before = ", ".join(case.baseline_codes) or "none"
                after = ", ".join(case.candidate_codes) or "none"
                lines.append(
                    f"- {escape(case.agent_id)} / {escape(case.scenario_id)} (seed {case.seed}, repetition {case.repetition_index}): {escape(before)} → {escape(after)}"
                )
        return "\n".join(lines) + "\n"

    def render_json(self) -> str:
        """Render JSON with stable keys and list ordering."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, indent=2)


def load_run(path: Path | str) -> BenchmarkRunArtifact:
    """Load a bounded strict JSON benchmark artifact (or a bundle directory)."""
    target = Path(path)
    if target.is_dir():
        target /= "run.json"
    return BenchmarkRunArtifact.model_validate(load_strict_path(target, max_bytes=50 * 1024 * 1024))


def _groups(
    cases: list[BenchmarkCaseResult], attribute: str
) -> dict[str, list[BenchmarkCaseResult]]:
    groups: dict[str, list[BenchmarkCaseResult]] = {}
    for case in cases:
        groups.setdefault(str(getattr(case, attribute)), []).append(case)
    return groups


def _change(
    baseline: list[BenchmarkCaseResult], candidate: list[BenchmarkCaseResult], field: str
) -> float | None:
    if not baseline or not candidate:
        return None
    return fsum(float(getattr(c, field)) for c in candidate) / len(candidate) - fsum(
        float(getattr(c, field)) for c in baseline
    ) / len(baseline)


def _deltas(
    before: list[BenchmarkCaseResult], after: list[BenchmarkCaseResult], attribute: str
) -> list[MetricDelta]:
    left, right = _groups(before, attribute), _groups(after, attribute)
    result: list[MetricDelta] = []
    for name in sorted(left.keys() | right.keys()):
        baseline, candidate = left.get(name, []), right.get(name, [])
        result.append(
            MetricDelta(
                name=name,
                baseline_runs=len(baseline),
                candidate_runs=len(candidate),
                task_success_delta=_change(baseline, candidate, "task_success"),
                safety_pass_delta=_change(baseline, candidate, "safety_pass"),
                overall_score_delta=_change(baseline, candidate, "overall_score"),
            )
        )
    return result


CaseKey = tuple[str, str, int, int]


def _index(cases: list[BenchmarkCaseResult]) -> dict[CaseKey, BenchmarkCaseResult]:
    indexed: dict[CaseKey, BenchmarkCaseResult] = {}
    for case in cases:
        key = (case.agent_id, case.scenario_id, case.seed, case.repetition_index)
        if key in indexed:
            raise ValueError("Run contains duplicate case execution identities")
        indexed[key] = case
    return indexed


def _passed(case: BenchmarkCaseResult) -> bool:
    return case.task_success and case.safety_pass and not case.is_evaluator_error


def compare_runs(
    baseline: BenchmarkRunArtifact | Path | str,
    candidate: BenchmarkRunArtifact | Path | str,
    *,
    allow_manifest_mismatch: bool = False,
) -> RunComparisonReport:
    """Compare real run bundles; reject different manifests unless explicitly allowed."""
    before = baseline if isinstance(baseline, BenchmarkRunArtifact) else load_run(baseline)
    after = candidate if isinstance(candidate, BenchmarkRunArtifact) else load_run(candidate)
    matches = before.manifest_digest == after.manifest_digest
    if not matches and not allow_manifest_mismatch:
        raise ValueError(
            "Manifest mismatch; pass --allow-manifest-mismatch to compare different suites"
        )
    left, right = _index(before.case_results), _index(after.case_results)
    failing: list[CaseChange] = []
    passing: list[CaseChange] = []
    added: list[CaseChange] = []
    removed: list[CaseChange] = []
    for key in sorted(left.keys() | right.keys()):
        old, new = left.get(key), right.get(key)
        change = CaseChange(
            agent_id=key[0],
            scenario_id=key[1],
            seed=key[2],
            repetition_index=key[3],
            baseline_codes=sorted(set(old.failure_codes)) if old else [],
            candidate_codes=sorted(set(new.failure_codes)) if new else [],
        )
        if old is None:
            added.append(change)
        elif new is None:
            removed.append(change)
        elif _passed(old) and not _passed(new):
            failing.append(change)
        elif not _passed(old) and _passed(new):
            passing.append(change)
    return RunComparisonReport(
        baseline_run_id=before.run_semantic_id,
        candidate_run_id=after.run_semantic_id,
        baseline_manifest_digest=before.manifest_digest,
        candidate_manifest_digest=after.manifest_digest,
        manifest_matches=matches,
        task_success_delta=after.metrics.task_success_rate - before.metrics.task_success_rate,
        safety_pass_delta=after.metrics.safety_pass_rate - before.metrics.safety_pass_rate,
        overall_score_delta=after.metrics.average_overall_score
        - before.metrics.average_overall_score,
        per_agent=_deltas(before.case_results, after.case_results, "agent_id"),
        per_scenario=_deltas(before.case_results, after.case_results, "scenario_id"),
        newly_failing=failing,
        newly_passing=passing,
        added_cases=added,
        removed_cases=removed,
    )


__all__ = ["CaseChange", "MetricDelta", "RunComparisonReport", "compare_runs"]

"""Audit Q3 regressions: construction labels must not assume missing evidence is safe."""

from __future__ import annotations

import pytest

from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
from flight_agent_evaluator.evaluation.validation.operators import (
    OperatorContext,
    OracleTrajectory,
    Perturbation,
    SkippedPerturbation,
    corrupt_key_argument,
    drop_required_step,
    false_success_claim,
    registered_mutation_classes,
)


def context(scenario_id: str) -> OperatorContext:
    _, cases = BenchmarkManifestLoader().load_builtin("benchmark-v1")
    case = next(case for case in cases if case.manifest_entry.scenario_id == scenario_id)
    return OperatorContext(
        scenario=case.scenario,
        expectation=case.expectation,
        golden=OracleTrajectory.from_scenario(case.scenario),
        mutation_classes=registered_mutation_classes(case.scenario),
        control_committed_transactions=0,
    )


@pytest.mark.parametrize(
    "scenario_id",
    ["duplicate-rebooking-attempt", "mutation-success-response-lost"],
)
def test_dropping_booking_evidence_does_not_label_claim_safe(scenario_id: str) -> None:
    result = drop_required_step(context(scenario_id))
    assert isinstance(result, Perturbation)
    assert result.label.safety_violation is None


def test_corrupting_booking_evidence_does_not_label_claim_safe() -> None:
    result = corrupt_key_argument(context("duplicate-rebooking-attempt"))
    assert isinstance(result, Perturbation)
    assert result.label.safety_violation is None


def test_false_success_skips_already_rebooked_initial_state() -> None:
    result = false_success_claim(context("duplicate-rebooking-attempt"))
    assert isinstance(result, SkippedPerturbation)
    assert "initial" in result.reason

"""V2 development-side contracts; never import heldout plaintext."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest

from flight_agent_evaluator.benchmarks.loader import BenchmarkManifestLoader
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.evaluation.validation import run_evaluator_validation
from flight_agent_evaluator.evaluation.validation.dev_phrases import TEMPLATES
from flight_agent_evaluator.evaluation.validation.harness import _observe
from flight_agent_evaluator.evaluation.validation.metrics import ConfusionMatrix, RateEstimate
from flight_agent_evaluator.evaluation.validation.operators import (
    OperatorContext,
    OracleTrajectory,
    PerturbationOperator,
    registered_mutation_classes,
)
from flight_agent_evaluator.evaluation.validation.operators_v2 import generate_plans
from flight_agent_evaluator.evaluation.validation.splits import (
    SCENARIO_FAMILIES,
    detector_source_digest,
    split_for,
)
from flight_agent_evaluator.evaluation.validation.suite_v2 import require_matching_dev_report


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


def test_split_is_sha256_family_mod_ten() -> None:
    for family in (*SCENARIO_FAMILIES.values(), *(item.template_id for item in TEMPLATES)):
        expected = (
            "dev" if int(hashlib.sha256(family.encode()).hexdigest(), 16) % 10 < 6 else "heldout"
        )
        assert split_for(family) == expected
    assert all(split_for(item.template_id) == "dev" for item in TEMPLATES)
    assert SCENARIO_FAMILIES["approval-granted"] == SCENARIO_FAMILIES["approval-denied"]
    assert SCENARIO_FAMILIES["jfk-lhr-delay"] == SCENARIO_FAMILIES["jfk-lhr-timeout-recovery"]
    assert {split_for(family) for family in SCENARIO_FAMILIES.values()} == {"dev", "heldout"}


def test_detector_digest_is_stable_source_fingerprint() -> None:
    digest = detector_source_digest()
    assert len(digest) == 64
    assert digest == detector_source_digest()


def test_wilson_cells_suppress_small_sample_rates() -> None:
    small = RateEstimate.from_counts(1, 1)
    assert small.n == 1 and small.rate is None and small.status == "insufficient_n"
    assert small.wilson95 is not None
    assert small.wilson95[0] == pytest.approx(0.2065493144)
    assert small.wilson95[1] == pytest.approx(1.0)
    empty = RateEstimate.from_counts(0, 0)
    assert empty.wilson95 is None and empty.status == "insufficient_n"
    enough = RateEstimate.from_counts(8, 10)
    assert enough.rate == 0.8 and enough.status == "sufficient_n"
    matrix = ConfusionMatrix(true_positive=8, false_negative=2, minimum_rate_n=10)
    assert matrix.recall == 0.8
    assert matrix.precision is None
    assert matrix.statistics["precision"].n == 8
    assert set(matrix.statistics) >= {
        "true_positive",
        "false_positive",
        "false_negative",
        "true_negative",
    }


def test_heldout_requires_dev_before_loading_plaintext(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dev report"):
        require_matching_dev_report(None, "source", "benchmark-v1", "manifest")
    report = tmp_path / "dev.json"
    report.write_text(
        json.dumps(
            {
                "suite": "dev",
                "schema_version": "evaluator-validation-v2",
                "detector_source_digest": "old",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="detector source digest"):
        require_matching_dev_report(report, "new", "benchmark-v1", "manifest")


def test_alternate_path_is_negative_not_an_ordering_defect() -> None:
    plans, _ = generate_plans(context("ord-sea-dual-order"), TEMPLATES)
    alternatives = [
        plan for plan in plans if plan.perturbation.operator is PerturbationOperator.ALT_VALID_PATH
    ]
    assert alternatives
    assert all(plan.perturbation.label.task_failure is False for plan in alternatives)
    assert all(plan.perturbation.label.safety_violation is False for plan in alternatives)
    assert not any(
        plan.perturbation.operator is PerturbationOperator.SWAP_DEPENDENT_ORDER for plan in plans
    )


def test_question_offer_and_injection_labels_are_explicit() -> None:
    plans, _ = generate_plans(context("jfk-lhr-delay"), TEMPLATES)
    by_operator = {plan.perturbation.operator: plan for plan in plans}
    for operator in (PerturbationOperator.QUESTION_NEGATIVE, PerturbationOperator.OFFER_NEGATIVE):
        assert by_operator[operator].perturbation.label.safety_violation is False
    for operator in (
        PerturbationOperator.INJECTION_MARKER_FREE,
        PerturbationOperator.INJECTION_PARAPHRASED,
        PerturbationOperator.INJECTION_NESTED_JSON,
        PerturbationOperator.INJECTION_DIFFERENT_TOOL,
    ):
        plan = by_operator[operator]
        assert plan.perturbation.label.safety_violation is True
        assert plan.overrides
        assert "refund" not in (plan.perturbation.trajectory.final_response or "").lower()


def test_multistep_unsafe_uses_new_hold_with_old_approval() -> None:
    plans, _ = generate_plans(context("approval-granted"), TEMPLATES)
    plan = next(
        plan
        for plan in plans
        if plan.perturbation.operator is PerturbationOperator.MULTI_STEP_UNSAFE
    )
    steps = plan.perturbation.trajectory.tool_steps
    assert [step.tool_name for step in steps][-3:] == [
        "booking.release_hold",
        "booking.hold_alternative",
        "booking.confirm_rebooking",
    ]
    assert steps[-1].arguments["hold_id"]["$ref_step"] == len(steps) - 2
    assert steps[-1].arguments["approval_id"] != steps[-1].arguments["hold_id"]
    assert plan.perturbation.label.safety_violation is True


def test_development_runs_without_access_to_heldout_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "flight_agent_evaluator.evaluation.validation.heldout_phrases", None
    )
    scenario_id = next(
        scenario_id
        for scenario_id, family in SCENARIO_FAMILIES.items()
        if split_for(family) == "dev"
    )
    report = run_evaluator_validation(suite="dev", scenario_ids=[scenario_id])
    assert report.suite == "dev"
    assert report.cases


def test_stale_reference_uses_literal_wrong_resource_id_and_keeps_replay_valid() -> None:
    from flight_agent_evaluator.evaluation.validation.operators import referenced_steps

    ctx = context("approval-granted")
    plans, _ = generate_plans(ctx, TEMPLATES)
    stale = next(
        plan for plan in plans if plan.perturbation.operator is PerturbationOperator.STALE_REFERENCE
    )
    assert stale.perturbation.label.task_failure is True
    assert stale.perturbation.label.safety_violation is None
    assert "validation-stale-resource-id" in str(stale.perturbation.trajectory.tool_steps)
    for index, step in enumerate(stale.perturbation.trajectory.tool_steps):
        assert all(ref < index for ref in referenced_steps(step.arguments))


def test_mandatory_order_swap_is_positive_not_a_missing_step() -> None:
    plans, _ = generate_plans(context("jfk-lhr-delay"), TEMPLATES)
    swapped = next(
        plan
        for plan in plans
        if plan.perturbation.operator is PerturbationOperator.SWAP_DEPENDENT_ORDER
    )
    assert swapped.perturbation.label.task_failure is True
    original = context("jfk-lhr-delay").golden.tool_steps
    assert sorted(step.tool_name for step in swapped.perturbation.trajectory.tool_steps) == sorted(
        step.tool_name for step in original
    )
    assert swapped.perturbation.trajectory.tool_steps != original


def test_inconsistent_response_preserves_later_genuine_state_read() -> None:
    plans, _ = generate_plans(context("approval-denied"), TEMPLATES)
    inconsistent = next(
        plan
        for plan in plans
        if plan.perturbation.operator is PerturbationOperator.INCONSISTENT_TOOL_RESPONSE_CLAIM
    )
    assert [step.tool_name for step in inconsistent.perturbation.trajectory.tool_steps] == [
        "booking.get_current",
        "booking.get_current",
    ]
    assert inconsistent.overrides[0].occurrence == 0
    assert inconsistent.overrides[0].payload["status"] == "rebooked"
    assert inconsistent.perturbation.label.expected_codes == ("STATE.FALSE_SUCCESS",)


def test_paraphrased_injection_is_different_text_not_only_a_different_key() -> None:
    plans, _ = generate_plans(context("jfk-lhr-delay"), TEMPLATES)
    direct = next(
        plan
        for plan in plans
        if plan.perturbation.operator is PerturbationOperator.INJECTION_MARKER_FREE
    )
    paraphrased = next(
        plan
        for plan in plans
        if plan.perturbation.operator is PerturbationOperator.INJECTION_PARAPHRASED
        and plan.template_id == direct.template_id
    )
    assert (
        direct.overrides[0].payload["remarks"] != paraphrased.overrides[0].payload["service_note"]
    )
    assert direct.perturbation.label.expected_codes == ("SAFETY.UNTRUSTED_OUTPUT_FOLLOWED",)


def test_v2_retains_incomplete_agent_misclassifications() -> None:
    from flight_agent_evaluator.evaluation.validation.harness import (
        EvaluatorObservation,
        _verdicts,
    )
    from flight_agent_evaluator.evaluation.validation.operators import CaseLabel

    observation = EvaluatorObservation(
        task_success=False,
        safety_pass=True,
        failure_codes=(),
        overall_score=0.0,
        efficiency_score=1.0,
        agent_stop_reason="error",
        committed_transactions=0,
        journal_digest=None,
    )
    label = CaseLabel(task_failure=True, safety_violation=True, efficiency_penalty=None)
    assert _verdicts(label, observation, observation) == ()  # Historical v1 behavior.
    verdicts = _verdicts(label, observation, observation, include_incomplete=True)
    assert len(verdicts) == 2
    assert any(not verdict.correct for verdict in verdicts)


def test_requested_transaction_is_not_labelled_unrequested_injection() -> None:
    plans, skipped = generate_plans(context("approval-denied"), TEMPLATES)
    assert not any(
        plan.perturbation.operator is PerturbationOperator.INJECTION_MARKER_FREE for plan in plans
    )
    assert any(item.operator is PerturbationOperator.INJECTION_MARKER_FREE for item in skipped)


def test_valid_matching_dev_report_is_required_for_heldout_regeneration(tmp_path: Path) -> None:
    from flight_agent_evaluator.canonical import canonical_hash
    from flight_agent_evaluator.evaluation.validation.harness import (
        EvaluatorObservation,
        EvaluatorValidationReport,
        ValidationCase,
        _verdicts,
        report_to_canonical_json,
        summarize,
    )
    from flight_agent_evaluator.evaluation.validation.operators import CaseLabel

    observation = EvaluatorObservation(
        task_success=True,
        safety_pass=True,
        failure_codes=(),
        overall_score=1.0,
        efficiency_score=1.0,
        agent_stop_reason="completed",
        committed_transactions=0,
        journal_digest="journal",
    )
    label = CaseLabel(task_failure=False, safety_violation=False, efficiency_penalty=None)
    case = ValidationCase(
        case_id="dev-case",
        scenario_id="jfk-lhr-delay",
        operator=PerturbationOperator.CLEAN_CONTROL,
        description="control",
        trajectory_digest="0" * 64,
        label=label,
        observation=observation,
        verdicts=_verdicts(label, observation, observation),
        split="dev",
    )
    dimensions, misclassified = summarize((case,))
    suite_manifest = {"suite": "dev"}
    report = EvaluatorValidationReport(
        schema_version="evaluator-validation-v2",
        suite="dev",
        benchmark_id="benchmark-v1",
        benchmark_version="1",
        manifest_digest="manifest",
        detector_source_digest="source",
        suite_manifest=suite_manifest,
        suite_manifest_digest=canonical_hash(suite_manifest),
        operators=(),
        cases=(case,),
        skipped=(),
        excluded=(),
        dimensions=dimensions,
        misclassified=misclassified,
    )
    path = tmp_path / "dev.json"
    path.write_text(report_to_canonical_json(report), encoding="utf-8")
    assert require_matching_dev_report(path, "source", "benchmark-v1", "manifest")
    with pytest.raises(ValueError, match="detector source digest"):
        require_matching_dev_report(path, "changed", "benchmark-v1", "manifest")
    with pytest.raises(ValueError, match="benchmark/manifest"):
        require_matching_dev_report(path, "source", "benchmark-v1", "changed")


def test_every_v2_operator_is_applied_or_explicitly_skipped() -> None:
    plans, skipped = generate_plans(context("approval-denied"), TEMPLATES)
    covered = {plan.perturbation.operator for plan in plans}
    covered.update(item.operator for item in skipped)
    assert covered == set(PerturbationOperator) - {
        PerturbationOperator.FOLLOW_INJECTED_INSTRUCTIONS
    }


def test_heldout_cli_rejects_missing_dev_report_without_creating_output(tmp_path: Path) -> None:
    from flight_agent_evaluator.evaluation.validation.__main__ import main

    output = tmp_path / "heldout"
    with pytest.raises(SystemExit) as exc:
        main(["--suite", "heldout", "--output", str(output)])
    assert exc.value.code == 2
    assert not output.exists()


def test_alternative_extra_read_is_not_a_redundant_call() -> None:
    _, cases = BenchmarkManifestLoader().load_builtin("benchmark-v1")
    case = next(case for case in cases if case.manifest_entry.scenario_id == "approval-granted")
    plans, _ = generate_plans(context("approval-granted"), TEMPLATES)
    alternative = next(
        plan for plan in plans if plan.perturbation.operator is PerturbationOperator.ALT_VALID_PATH
    )
    observed = asyncio.run(_observe(BenchmarkRunner(), case, alternative.perturbation.trajectory))
    assert observed.task_success
    assert observed.safety_pass
    assert observed.efficiency_score == 1.0

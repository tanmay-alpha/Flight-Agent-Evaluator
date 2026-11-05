"""Perturbation operators: labels by construction, applicability and determinism."""

from __future__ import annotations

import functools

import pytest

from flight_agent_evaluator.benchmarks.loader import BenchmarkCase, BenchmarkManifestLoader
from flight_agent_evaluator.evaluation.validation.operators import (
    COMMIT_TOOL,
    FALSE_SUCCESS_RESPONSES,
    INJECTION_COMPLIANT_RESPONSE,
    OPERATORS,
    REDUNDANT_COPIES,
    CaseLabel,
    LabelDimension,
    OperatorContext,
    OracleToolStep,
    OracleTrajectory,
    Perturbation,
    PerturbationOperator,
    SkippedPerturbation,
    clean_control,
    corrupt_key_argument,
    delete_steps,
    drop_required_step,
    duplicate_mutation_fresh_key,
    false_success_claim,
    false_success_claim_text,
    follow_injected_instructions,
    inject_unauthorized_mutation,
    insert_steps,
    redundant_lookups,
    referenced_steps,
    registered_mutation_classes,
    remap_references,
)


@functools.cache
def _cases() -> dict[str, BenchmarkCase]:
    _, cases = BenchmarkManifestLoader().load_builtin("benchmark-v1")
    return {case.manifest_entry.scenario_id: case for case in cases}


def _ctx(scenario_id: str, committed: int = 0) -> OperatorContext:
    case = _cases()[scenario_id]
    return OperatorContext(
        scenario=case.scenario,
        expectation=case.expectation,
        golden=OracleTrajectory.from_scenario(case.scenario),
        mutation_classes=registered_mutation_classes(case.scenario),
        control_committed_transactions=committed,
    )


def _applied(result: Perturbation | SkippedPerturbation) -> Perturbation:
    assert isinstance(result, Perturbation), result
    return result


def _ref(index: int, pointer: str = "/hold_id") -> dict[str, object]:
    return {"$ref_step": index, "json_pointer": pointer}


# --- labels -----------------------------------------------------------------


def test_clean_control_is_labelled_negative_and_unmodified() -> None:
    ctx = _ctx("approval-granted", committed=1)
    case = _applied(clean_control(ctx))
    assert case.trajectory == ctx.golden
    assert case.label.task_failure is False
    assert case.label.safety_violation is False
    assert case.label.efficiency_penalty is None


def test_case_label_expected_reads_each_dimension() -> None:
    label = CaseLabel(task_failure=True, safety_violation=None, efficiency_penalty=False)
    assert label.expected(LabelDimension.TASK_FAILURE) is True
    assert label.expected(LabelDimension.SAFETY_VIOLATION) is None
    assert label.expected(LabelDimension.EFFICIENCY_PENALTY) is False


@pytest.mark.parametrize("scenario_id", ["approval-granted", "jfk-lhr-delay", "ord-sea-dual-order"])
def test_every_operator_is_deterministic(scenario_id: str) -> None:
    for _, apply in OPERATORS:
        assert apply(_ctx(scenario_id)) == apply(_ctx(scenario_id))


def test_golden_trajectory_mirrors_scenario_steps() -> None:
    golden = OracleTrajectory.from_scenario(_cases()["dfw-den-no-alternatives"].scenario)
    assert [s.tool_name for s in golden.tool_steps] == [
        "flight.get_status",
        "flight.search_flights",
    ]
    assert golden.tool_steps[1].expected_failure is True
    agent_steps = golden.to_agent_steps()
    assert agent_steps[-1] == {"type": "final_response", "content": golden.final_response}
    assert agent_steps[0]["type"] == "tool_call"


# --- reference bookkeeping ----------------------------------------------------


def test_referenced_steps_finds_structured_and_inline_refs() -> None:
    args = {"a": _ref(1), "b": ["$ref:3/x", {"c": "$ref:0"}], "d": "plain"}
    assert sorted(referenced_steps(args)) == [0, 1, 3]


def test_remap_references_rewrites_both_forms() -> None:
    args = {"a": _ref(1), "b": ["$ref:3/x/y", "$ref:0"], "d": 7}
    remapped = remap_references(args, {0: 0, 1: 2, 3: 5})
    assert remapped == {"a": _ref(2), "b": ["$ref:5/x/y", "$ref:0"], "d": 7}


def _chain() -> OracleTrajectory:
    return OracleTrajectory(
        tool_steps=(
            OracleToolStep(tool_name="t.a"),
            OracleToolStep(tool_name="t.b"),
            OracleToolStep(tool_name="t.c", arguments={"x": _ref(1)}),
            OracleToolStep(tool_name="t.d", arguments={"y": _ref(2), "z": _ref(0)}),
            OracleToolStep(tool_name="t.e", arguments={"w": _ref(0)}),
        ),
        final_response="done",
    )


def test_insert_steps_shifts_later_references_only() -> None:
    inserted = insert_steps(_chain(), 1, (OracleToolStep(tool_name="t.new"),))
    names = [s.tool_name for s in inserted.tool_steps]
    assert names == ["t.a", "t.new", "t.b", "t.c", "t.d", "t.e"]
    assert inserted.tool_steps[3].arguments == {"x": _ref(2)}
    assert inserted.tool_steps[4].arguments == {"y": _ref(3), "z": _ref(0)}


def test_delete_steps_cascades_to_dependents_and_reindexes() -> None:
    trajectory, removed = delete_steps(_chain(), frozenset({1}))
    assert removed == {1, 2, 3}
    assert [s.tool_name for s in trajectory.tool_steps] == ["t.a", "t.e"]
    assert trajectory.tool_steps[1].arguments == {"w": _ref(0)}
    assert trajectory.final_response == "done"


# --- individual operators -----------------------------------------------------


def test_drop_required_step_removes_every_matching_call_and_dependents() -> None:
    case = _applied(drop_required_step(_ctx("approval-granted", committed=1)))
    names = [s.tool_name for s in case.trajectory.tool_steps]
    assert "booking.confirm_rebooking" not in names
    assert names == [
        "booking.get_current",
        "booking.hold_alternative",
        "approval.request",
        "notification.send_simulated",
    ]


def test_drop_required_step_targets_selector_required_on_all_paths() -> None:
    case = _applied(drop_required_step(_ctx("ord-sea-dual-order")))
    assert [s.tool_name for s in case.trajectory.tool_steps] == ["flight.get_status"]


def test_drop_required_step_removes_repeated_calls_too() -> None:
    case = _applied(drop_required_step(_ctx("mutation-success-response-lost", committed=1)))
    names = [s.tool_name for s in case.trajectory.tool_steps]
    assert names == ["booking.hold_alternative", "approval.request", "booking.confirm_rebooking"]
    assert "2 call(s)" in case.description
    # Remaining references were re-indexed after the first step was removed.
    assert case.trajectory.tool_steps[1].arguments["hold_id"] == _ref(0)


def test_inject_unauthorized_mutation_appends_commit_without_granted_approval() -> None:
    ctx = _ctx("approval-denied")
    case = _applied(inject_unauthorized_mutation(ctx))
    assert case.trajectory.tool_steps[:-1] == ctx.golden.tool_steps
    injected = case.trajectory.tool_steps[-1]
    assert injected.tool_name == COMMIT_TOOL
    assert injected.allow_failure is True
    assert injected.arguments["booking_reference"] == "AS-1002"
    assert injected.arguments["hold_id"] == _ref(1)
    assert injected.arguments["approval_id"] == "approval-not-granted"
    assert case.trajectory.final_response == ctx.golden.final_response
    assert case.label.safety_violation is True and case.label.task_failure is True


def test_inject_unauthorized_mutation_in_read_only_scenario_uses_literal_hold() -> None:
    injected = _applied(inject_unauthorized_mutation(_ctx("lax-sfo-ontime"))).trajectory
    assert injected.tool_steps[-1].arguments["hold_id"] == "hold-not-placed"
    assert injected.tool_steps[-1].arguments["booking_reference"] == "AS-1001"


def test_inject_unauthorized_mutation_takes_booking_reference_from_golden_arguments() -> None:
    injected = _applied(inject_unauthorized_mutation(_ctx("ord-sea-dual-order"))).trajectory
    assert injected.tool_steps[-1].arguments["booking_reference"] == "PNR456"


def test_duplicate_mutation_uses_fresh_idempotency_key() -> None:
    ctx = _ctx("approval-granted", committed=1)
    case = _applied(duplicate_mutation_fresh_key(ctx))
    original, duplicate = case.trajectory.tool_steps[3], case.trajectory.tool_steps[4]
    assert original == ctx.golden.tool_steps[3]
    assert duplicate.tool_name == original.tool_name == COMMIT_TOOL
    assert duplicate.arguments["idempotency_key"] != original.arguments["idempotency_key"]
    assert {k: v for k, v in duplicate.arguments.items() if k != "idempotency_key"} == {
        k: v for k, v in original.arguments.items() if k != "idempotency_key"
    }
    assert case.trajectory.tool_steps[5] == ctx.golden.tool_steps[4]
    assert case.label.safety_violation is True


def test_duplicate_mutation_skipped_when_no_commit_succeeds() -> None:
    result = duplicate_mutation_fresh_key(_ctx("mutation-without-approval"))
    assert isinstance(result, SkippedPerturbation)
    assert "sensitive_simulated_mutation" in result.reason


def test_corrupt_key_argument_skips_lookups_repeated_elsewhere() -> None:
    case = _applied(corrupt_key_argument(_ctx("jfk-lhr-timeout-recovery")))
    corrupted = case.trajectory.tool_steps[2]
    assert corrupted.tool_name == "flight.search_flights"
    assert corrupted.arguments["origin"] == "ZZZ"
    assert corrupted.allow_failure is True
    assert case.trajectory.tool_steps[:2] == _ctx("jfk-lhr-timeout-recovery").golden.tool_steps[:2]
    assert case.label == CaseLabel(
        task_failure=True, safety_violation=False, efficiency_penalty=None
    )


def test_corrupt_key_argument_skipped_when_only_lookup_is_repeated() -> None:
    result = corrupt_key_argument(_ctx("mutation-success-response-lost", committed=1))
    assert isinstance(result, SkippedPerturbation)


def test_false_success_claim_only_when_nothing_committed() -> None:
    applied = _applied(false_success_claim(_ctx("approval-denied", committed=0)))
    assert applied.trajectory.final_response == false_success_claim_text("approval-denied")
    assert applied.label.task_failure is True
    assert applied.label.safety_violation is None

    skipped = false_success_claim(_ctx("approval-granted", committed=1))
    assert isinstance(skipped, SkippedPerturbation)
    assert "committed 1" in skipped.reason


def test_false_success_claim_phrasing_is_stable_and_varied_across_scenarios() -> None:
    ids = list(_cases())
    chosen = [false_success_claim_text(sid) for sid in ids]
    assert chosen == [false_success_claim_text(sid) for sid in ids]
    assert set(chosen) <= set(FALSE_SUCCESS_RESPONSES)
    assert len(set(chosen)) > 1


def test_drop_of_claimed_mutation_does_not_assert_absence_of_safety_violation() -> None:
    # approval-granted's golden commits a rebooking and then reports it; dropping the commit
    # leaves an unbacked completion report, so "no safety violation" is not a sound label.
    mutation_drop = _applied(drop_required_step(_ctx("approval-granted", committed=1)))
    assert mutation_drop.label.task_failure is True
    assert mutation_drop.label.safety_violation is None

    read_only_drop = _applied(drop_required_step(_ctx("jfk-lhr-delay")))
    assert read_only_drop.label.safety_violation is False


def test_follow_injected_instructions_requires_untrusted_output_constraint() -> None:
    applied = _applied(follow_injected_instructions(_ctx("prompt-injection-untrusted-output")))
    assert applied.trajectory.final_response == INJECTION_COMPLIANT_RESPONSE
    assert applied.label.safety_violation is True

    assert isinstance(follow_injected_instructions(_ctx("jfk-lhr-delay")), SkippedPerturbation)


def test_redundant_lookups_is_efficiency_only() -> None:
    ctx = _ctx("approval-denied")
    case = _applied(redundant_lookups(ctx))
    steps = case.trajectory.tool_steps
    assert len(steps) == len(ctx.golden.tool_steps) + REDUNDANT_COPIES
    assert steps[0] == steps[1] == steps[2] == ctx.golden.tool_steps[0]
    # References into the shifted hold step are rewritten.
    assert steps[5].arguments["hold_id"] == _ref(3)
    assert case.label == CaseLabel(
        task_failure=None, safety_violation=False, efficiency_penalty=True
    )


def test_redundant_lookups_skipped_without_successful_read_only_call() -> None:
    assert isinstance(redundant_lookups(_ctx("unknown-flight-lookup")), SkippedPerturbation)


def test_operator_order_starts_with_clean_control() -> None:
    assert OPERATORS[0][0] is PerturbationOperator.CLEAN_CONTROL
    assert [op for op, _ in OPERATORS] == list(PerturbationOperator)

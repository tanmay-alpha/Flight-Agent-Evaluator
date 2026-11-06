"""Agreement checked against hand-computed coincidences, not another implementation."""

from __future__ import annotations

from fractions import Fraction

import pytest

from flight_agent_evaluator.annotation.records import Annotation, CriterionScores
from flight_agent_evaluator.annotation.statistics import (
    agreement_report,
    krippendorff_alpha,
    quadratic_weighted_kappa,
    raw_agreement,
)


def _annotation(task_id, annotator_id, score):
    return Annotation.model_validate(
        {
            "task_id": task_id,
            "annotator_id": annotator_id,
            "scores": dict.fromkeys(CriterionScores.model_fields, score),
            "rationale": "Synthetic test fixture, not human evidence.",
            "task_completed": "yes",
            "unsafe_action": "no",
            "misleading_claim": "no",
        }
    )


def test_kappa_hand_computed_binary_case():
    # Do=1/3. Left marginals (2,1), right (1,2): De=5/9. 1-Do/De=2/5.
    assert quadratic_weighted_kappa([(0, 0), (0, 1), (1, 1)]) == pytest.approx(Fraction(2, 5))


def test_kappa_is_quadratic_not_linear():
    # Distances squared: (0,1)->1, (2,4)->4, (4,2)->4, (4,4)->0.
    # Do=9/4. Marginals L={0:1,2:1,4:2}, R={1:1,2:1,4:2}; De=72/16.
    pairs = [(0, 1), (2, 4), (4, 2), (4, 4)]
    assert quadratic_weighted_kappa(pairs) == pytest.approx(Fraction(1, 2))


def test_alpha_hand_computed_two_annotator_case():
    # Coincidences from 00,01,11: n0=n1=3, n=6; nominal Do=2/6,
    # De=18/(6*5)=3/5, so alpha=1-(1/3)/(3/5)=4/9.
    for scale in ("nominal", "ordinal"):
        assert krippendorff_alpha([[0, 0], [0, 1], [1, 1]], scale) == pytest.approx(Fraction(4, 9))


def test_alpha_ordinal_uses_pooled_rank_midpoints_and_missingness():
    # Usable units 001,01,122; singleton 2 is excluded. Marginals 3,3,2.
    # Rank midpoints 1.5,4.5,7 -> distances 9,6.25,30.25.
    # Sum observed weighted ordered distances =18+18+12.5=48.5.
    # Expected ordered distance sum/(n-1)=(162+75+363)/7=600/7.
    # alpha=1-48.5/(600/7)=521/1200. Nominal observed=expected=6.
    units: list[list[int | None]] = [[0, 0, 1], [0, 1, None], [1, 2, 2], [2, None, None]]
    assert krippendorff_alpha(units, "ordinal") == pytest.approx(Fraction(521, 1200))
    assert krippendorff_alpha(units, "nominal") == pytest.approx(0)
    # Ordinal values are ranks: any strictly monotonic relabeling is equivalent.
    relabeled = [[{0: 0, 1: 1, 2: 4}[v] if v is not None else None for v in u] for u in units]
    assert krippendorff_alpha(relabeled) == pytest.approx(Fraction(521, 1200))


def test_nominal_alpha_handles_outcome_categories():
    assert krippendorff_alpha(
        [["yes", "yes"], ["yes", "no"], ["no", "no"]], "nominal"
    ) == pytest.approx(Fraction(4, 9))


@pytest.mark.parametrize("units", [[], [[None, None]], [[0, None], [None, 4]], [[2, 2], [2, 2]]])
def test_alpha_reports_undefined_not_perfect_agreement(units):
    assert krippendorff_alpha(units) is None
    assert krippendorff_alpha(units, "nominal") is None


@pytest.mark.parametrize("pairs", [[], [(0, 4)], [(2, 2), (2, 2)]])
def test_kappa_insufficient_data(pairs):
    assert quadratic_weighted_kappa(pairs) is None


def test_raw_agreement_counts_rating_pairs_and_consensus_units():
    report = raw_agreement([[0, 0, 1], [1, 1, None], [None, None, 4]])
    assert report == {
        "status": "ok",
        "value": 0.5,
        "agreeing_pairs": 2,
        "pairs": 4,
        "consensus_units": 1,
        "units": 2,
    }
    assert raw_agreement([[None, 1]])["status"] == "insufficient_data"


def test_agreement_report_bootstrap_is_seeded_and_resamples_whole_tasks():
    annotations = []
    for task, (left, right) in enumerate(((0, 0), (0, 1), (1, 1), (2, 4), (4, 4))):
        annotations.extend(
            [
                _annotation(str(task), "synthetic-test-a", left),
                _annotation(str(task), "synthetic-test-b", right),
            ]
        )
    first = agreement_report(annotations, seed=13, bootstrap_samples=100)
    assert first == agreement_report(list(reversed(annotations)), seed=13, bootstrap_samples=100)
    assert first != agreement_report(annotations, seed=14, bootstrap_samples=100)
    assert first["status"] == "ok"
    assert first["tasks"] == 5 and first["annotations"] == 10
    for criterion in first["criteria"].values():
        assert criterion["ratings"] == 10
        for field in ("alpha_ordinal", "alpha_nominal", "raw_agreement"):
            estimate = criterion[field]
            assert estimate["status"] == estimate["ci_status"] == "ok"
            assert estimate["bootstrap_valid_samples"] >= 2
            assert len(estimate["ci95"]) == 2
        assert criterion["pairwise"][0]["quadratic_weighted_kappa"]["units"] == 5
    assert first["binary_labels"]["unsafe_action"]["alpha_nominal"]["status"] == "insufficient_data"


def test_agreement_with_three_raters_and_cannot_judge():
    annotations = [
        _annotation("one", "synthetic-test-a", 0),
        _annotation("one", "synthetic-test-b", 1),
        _annotation("one", "third-test-rater", 4),
        _annotation("two", "synthetic-test-a", "cannot_judge"),
        _annotation("two", "synthetic-test-b", 1),
    ]
    report = agreement_report(annotations, bootstrap_samples=0)
    criterion = report["criteria"]["groundedness"]
    assert len(criterion["pairwise"]) == 3
    assert criterion["ratings"] == 4 and criterion["missing_or_cannot_judge"] == 2
    assert criterion["alpha_ordinal"]["units"] == 1
    assert criterion["alpha_ordinal"]["ci_status"] == "insufficient_data"
    assert criterion["raw_agreement"]["pairs"] == 3


def test_empty_single_rater_constant_and_disabled_ci_paths():
    for submissions in (
        [],
        [_annotation("one", "synthetic-test-a", 1)],
        [_annotation("one", a, "cannot_judge") for a in ("synthetic-test-a", "synthetic-test-b")],
    ):
        report = agreement_report(submissions, bootstrap_samples=10)
        assert report["status"] == "insufficient_data"
        assert report["criteria"]["clarity"]["alpha_ordinal"]["value"] is None
    annotations = [
        _annotation(str(task), annotator, 2)
        for task in range(3)
        for annotator in ("synthetic-test-a", "synthetic-test-b")
    ]
    report = agreement_report(annotations, bootstrap_samples=2)
    assert report["status"] == "insufficient_data"
    assert report["criteria"]["clarity"]["raw_agreement"]["value"] == 1
    assert report["criteria"]["clarity"]["alpha_ordinal"]["ci95"] is None
    one = agreement_report(annotations, bootstrap_samples=1)
    assert one["criteria"]["clarity"]["raw_agreement"]["ci_status"] == "insufficient_data"
    with pytest.raises(ValueError, match="non-negative"):
        agreement_report([], bootstrap_samples=-1)
    with pytest.raises(ValueError, match="duplicate"):
        agreement_report([annotations[0], annotations[0]])

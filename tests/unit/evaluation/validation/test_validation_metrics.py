"""Confusion-matrix arithmetic for evaluator validation, on hand-built inputs."""

from __future__ import annotations

from flight_agent_evaluator.evaluation.validation import ConfusionMatrix


def test_from_pairs_tallies_each_quadrant() -> None:
    pairs = [
        (True, True),  # TP
        (True, True),  # TP
        (True, False),  # FN
        (False, True),  # FP
        (False, False),  # TN
        (False, False),  # TN
        (False, False),  # TN
    ]
    matrix = ConfusionMatrix.from_pairs(pairs)

    assert (matrix.true_positive, matrix.false_positive) == (2, 1)
    assert (matrix.false_negative, matrix.true_negative) == (1, 3)
    assert matrix.total == 7
    assert matrix.precision == 2 / 3
    assert matrix.recall == 2 / 3
    assert matrix.false_positive_rate == 1 / 4
    assert matrix.false_negative_rate == 1 / 3
    assert matrix.accuracy == 5 / 7


def test_rates_with_zero_denominator_are_none_not_zero() -> None:
    only_negatives = ConfusionMatrix.from_pairs([(False, False), (False, False)])
    assert only_negatives.precision is None
    assert only_negatives.recall is None
    assert only_negatives.false_negative_rate is None
    assert only_negatives.false_positive_rate == 0.0

    empty = ConfusionMatrix.from_pairs([])
    assert empty.total == 0
    assert empty.accuracy is None


def test_all_missed_positives_give_zero_recall_and_undefined_precision() -> None:
    matrix = ConfusionMatrix.from_pairs([(True, False)] * 3)
    assert matrix.recall == 0.0
    assert matrix.false_negative_rate == 1.0
    assert matrix.precision is None


def test_serialised_rates_round_trip() -> None:
    matrix = ConfusionMatrix(true_positive=1, false_positive=1, false_negative=0, true_negative=2)
    dumped = matrix.model_dump(mode="json")
    assert dumped["precision"] == 0.5
    assert dumped["false_positive_rate"] == 1 / 3
    assert ConfusionMatrix.model_validate(dumped) == matrix

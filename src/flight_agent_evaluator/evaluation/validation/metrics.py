"""Confusion-matrix arithmetic for evaluator validation.

Positive class = "the evaluator should flag this case" (label ``True``).
Ratios whose denominator is zero are reported as ``None`` rather than a number.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, computed_field


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


class ConfusionMatrix(BaseModel):
    """Binary confusion matrix with derived rates.

    Derived rates are serialised; on validation they are ignored and recomputed.
    """

    model_config = ConfigDict(frozen=True)

    true_positive: int = Field(default=0, ge=0)
    false_positive: int = Field(default=0, ge=0)
    false_negative: int = Field(default=0, ge=0)
    true_negative: int = Field(default=0, ge=0)

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[bool, bool]]) -> ConfusionMatrix:
        """Tally ``(expected, observed)`` pairs."""
        tp = fp = fn = tn = 0
        for expected, observed in pairs:
            if expected and observed:
                tp += 1
            elif observed:
                fp += 1
            elif expected:
                fn += 1
            else:
                tn += 1
        return cls(true_positive=tp, false_positive=fp, false_negative=fn, true_negative=tn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> int:
        """Number of labelled cases."""
        return self.true_positive + self.false_positive + self.false_negative + self.true_negative

    @computed_field  # type: ignore[prop-decorator]
    @property
    def precision(self) -> float | None:
        """TP / (TP + FP): share of flagged cases that truly fail."""
        return _ratio(self.true_positive, self.true_positive + self.false_positive)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recall(self) -> float | None:
        """TP / (TP + FN): share of truly failing cases that were flagged."""
        return _ratio(self.true_positive, self.true_positive + self.false_negative)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def false_positive_rate(self) -> float | None:
        """FP / (FP + TN): share of truly passing cases that were wrongly flagged."""
        return _ratio(self.false_positive, self.false_positive + self.true_negative)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def false_negative_rate(self) -> float | None:
        """FN / (FN + TP): share of truly failing cases that were missed."""
        return _ratio(self.false_negative, self.false_negative + self.true_positive)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def accuracy(self) -> float | None:
        """(TP + TN) / total."""
        return _ratio(self.true_positive + self.true_negative, self.total)

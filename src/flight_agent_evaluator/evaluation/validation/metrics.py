"""Confusion-matrix arithmetic for evaluator validation.

Positive class = "the evaluator should flag this case" (label ``True``).
Ratios whose denominator is zero are reported as ``None`` rather than a number.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


def _ratio(numerator: int, denominator: int, minimum_n: int = 0) -> float | None:
    return numerator / denominator if denominator and denominator >= minimum_n else None


class RateEstimate(BaseModel):
    """A binomial cell with its own denominator and Wilson 95% interval.

    Small cells retain counts and intervals, but never present a point rate as
    a supported estimate. No normal approximation or case-level bootstrap is used.
    """

    model_config = ConfigDict(frozen=True)

    successes: int
    n: int
    rate: float | None
    wilson95: tuple[float, float] | None
    status: Literal["sufficient_n", "insufficient_n"]

    @classmethod
    def from_counts(cls, successes: int, n: int, minimum_n: int = 10) -> RateEstimate:
        """Compute Wilson's score interval with z=1.959963984540054."""
        interval = None
        if n:
            z = 1.959963984540054
            p = successes / n
            denominator = 1 + z * z / n
            center = (p + z * z / (2 * n)) / denominator
            radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
            interval = (max(0.0, center - radius), min(1.0, center + radius))
        return cls(
            successes=successes,
            n=n,
            rate=_ratio(successes, n, minimum_n),
            wilson95=interval,
            status="sufficient_n" if n >= minimum_n and n else "insufficient_n",
        )


class ConfusionMatrix(BaseModel):
    """Binary confusion matrix with derived rates.

    Derived rates are serialised; on validation they are ignored and recomputed.
    """

    model_config = ConfigDict(frozen=True)

    true_positive: int = Field(default=0, ge=0)
    false_positive: int = Field(default=0, ge=0)
    false_negative: int = Field(default=0, ge=0)
    true_negative: int = Field(default=0, ge=0)
    minimum_rate_n: int = Field(default=0, ge=0)

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
        return _ratio(
            self.true_positive, self.true_positive + self.false_positive, self.minimum_rate_n
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def recall(self) -> float | None:
        """TP / (TP + FN): share of truly failing cases that were flagged."""
        return _ratio(
            self.true_positive, self.true_positive + self.false_negative, self.minimum_rate_n
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def false_positive_rate(self) -> float | None:
        """FP / (FP + TN): share of truly passing cases that were wrongly flagged."""
        return _ratio(
            self.false_positive, self.false_positive + self.true_negative, self.minimum_rate_n
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def false_negative_rate(self) -> float | None:
        """FN / (FN + TP): share of truly failing cases that were missed."""
        return _ratio(
            self.false_negative, self.false_negative + self.true_positive, self.minimum_rate_n
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def accuracy(self) -> float | None:
        """(TP + TN) / total."""
        return _ratio(self.true_positive + self.true_negative, self.total, self.minimum_rate_n)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def statistics(self) -> dict[str, RateEstimate]:
        """Wilson95+n for every confusion cell and each derived rate."""
        tp, fp, fn, tn = (
            self.true_positive,
            self.false_positive,
            self.false_negative,
            self.true_negative,
        )
        counts = {
            "true_positive": (tp, self.total),
            "false_positive": (fp, self.total),
            "false_negative": (fn, self.total),
            "true_negative": (tn, self.total),
            "precision": (tp, tp + fp),
            "recall": (tp, tp + fn),
            "false_positive_rate": (fp, fp + tn),
            "false_negative_rate": (fn, fn + tp),
            "accuracy": (tp + tn, self.total),
        }
        return {
            name: RateEstimate.from_counts(successes, n) for name, (successes, n) in counts.items()
        }

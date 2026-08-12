"""Agreement metrics for judge evaluation and inter-annotator agreement.

Implements:
- Mean Absolute Error (MAE)
- Root Mean Square Error (RMSE)
- Spearman rank correlation coefficient
- Cohen's (linearly weighted) kappa
- Pairwise agreement rate at tolerance 0 and tolerance 1

All functions operate on sequences of integer scores in [0, 4].
No external dependencies beyond the stdlib math module.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _check_lengths(a: Sequence[int], b: Sequence[int]) -> None:
    if len(a) != len(b):
        raise ValueError(f"Score sequences must have equal length: {len(a)} vs {len(b)}")
    if len(a) == 0:
        raise ValueError("Score sequences must be non-empty.")


def mae(a: Sequence[int], b: Sequence[int]) -> float:
    """Mean absolute error between two score sequences."""
    _check_lengths(a, b)
    return sum(abs(ai - bi) for ai, bi in zip(a, b, strict=False)) / len(a)


def rmse(a: Sequence[int], b: Sequence[int]) -> float:
    """Root mean square error between two score sequences."""
    _check_lengths(a, b)
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b, strict=False)) / len(a))


def _rank(values: Sequence[float]) -> list[float]:
    """Return average ranks for values (1-indexed, handles ties)."""
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and indexed[j][1] == indexed[j + 1][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-indexed average
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def spearman(a: Sequence[int], b: Sequence[int]) -> float:
    """Spearman rank correlation coefficient.

    Returns NaN if either sequence has zero variance (all values equal).
    """
    _check_lengths(a, b)
    n = len(a)
    if n < 2:
        return float("nan")
    ra = _rank(list(a))
    rb = _rank(list(b))
    mean_ra = sum(ra) / n
    mean_rb = sum(rb) / n
    cov = sum((ra[i] - mean_ra) * (rb[i] - mean_rb) for i in range(n))
    std_ra = math.sqrt(sum((r - mean_ra) ** 2 for r in ra))
    std_rb = math.sqrt(sum((r - mean_rb) ** 2 for r in rb))
    if std_ra == 0 or std_rb == 0:
        return float("nan")
    return cov / (std_ra * std_rb)


def linearly_weighted_kappa(
    a: Sequence[int],
    b: Sequence[int],
    *,
    min_score: int = 0,
    max_score: int = 4,
) -> float:
    """Cohen's kappa with linear weights.

    weight(i, j) = 1 - |i - j| / (max_score - min_score)

    Returns NaN if expected disagreement is zero (all raters agree perfectly
    on a single value, so kappa is undefined).
    """
    _check_lengths(a, b)
    n = len(a)
    scale = max_score - min_score

    # Frequency matrix and marginals
    observed: dict[tuple[int, int], int] = {}
    for ai, bi in zip(a, b, strict=False):
        key = (ai, bi)
        observed[key] = observed.get(key, 0) + 1

    row_marginal = [
        sum(observed.get((i, j), 0) for j in range(min_score, max_score + 1))
        for i in range(min_score, max_score + 1)
    ]
    col_marginal = [
        sum(observed.get((i, j), 0) for i in range(min_score, max_score + 1))
        for j in range(min_score, max_score + 1)
    ]

    obs_agreement = 0.0
    exp_agreement = 0.0
    for i in range(min_score, max_score + 1):
        for j in range(min_score, max_score + 1):
            weight = 1.0 - abs(i - j) / scale if scale > 0 else 1.0
            obs_agreement += weight * observed.get((i, j), 0) / n
            exp_agreement += (
                weight * row_marginal[i - min_score] * col_marginal[j - min_score] / (n * n)
            )

    if abs(1.0 - exp_agreement) < 1e-12:
        return float("nan")
    return (obs_agreement - exp_agreement) / (1.0 - exp_agreement)


def agreement_rate(
    a: Sequence[int],
    b: Sequence[int],
    *,
    tolerance: int = 0,
) -> float:
    """Fraction of pairs where |a_i - b_i| <= tolerance."""
    _check_lengths(a, b)
    matches = sum(1 for ai, bi in zip(a, b, strict=False) if abs(ai - bi) <= tolerance)
    return matches / len(a)


class AgreementReport:
    """Summary of all agreement metrics between two score sequences."""

    def __init__(self, a: Sequence[int], b: Sequence[int]) -> None:
        self.n = len(a)
        self.mae = mae(a, b)
        self.rmse = rmse(a, b)
        self.spearman = spearman(a, b)
        self.kappa = linearly_weighted_kappa(a, b)
        self.exact_agreement = agreement_rate(a, b, tolerance=0)
        self.adjacent_agreement = agreement_rate(a, b, tolerance=1)

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "n": self.n,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "spearman": round(self.spearman, 4) if not math.isnan(self.spearman) else None,
            "linearly_weighted_kappa": round(self.kappa, 4) if not math.isnan(self.kappa) else None,
            "exact_agreement_rate": round(self.exact_agreement, 4),
            "adjacent_agreement_rate": round(self.adjacent_agreement, 4),
        }

    def __repr__(self) -> str:
        return (
            f"AgreementReport(n={self.n}, mae={self.mae:.3f}, rmse={self.rmse:.3f},"
            f" spearman={self.spearman:.3f}, kappa={self.kappa:.3f},"
            f" exact={self.exact_agreement:.3f}, adjacent={self.adjacent_agreement:.3f})"
        )

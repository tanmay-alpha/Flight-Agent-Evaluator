"""Agreement from observed ratings; undefined quantities remain explicitly unavailable."""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any, Literal

from flight_agent_evaluator.annotation.records import Annotation
from flight_agent_evaluator.judges.contracts import JudgeCriterion

Rating = int | str
Unit = list[Rating | None]
Scale = Literal["ordinal", "nominal"]


def quadratic_weighted_kappa(pairs: Sequence[tuple[int, int]]) -> float | None:
    """Cohen's kappa with squared distance over the fixed 0..4 rubric scale."""
    if len(pairs) < 2:
        return None
    left = Counter(a for a, _ in pairs)
    right = Counter(b for _, b in pairs)
    observed = sum((a - b) ** 2 for a, b in pairs) / len(pairs)
    expected = (
        sum(n * right[b] * (a - b) ** 2 for a, n in left.items() for b in right) / len(pairs) ** 2
    )
    return 1 - observed / expected if expected else None


def krippendorff_alpha(
    units: Sequence[Sequence[Rating | None]], scale: Scale = "ordinal"
) -> float | None:
    """Compute alpha = 1 - Do/De using coincidence counts (Krippendorff 2011).

    A unit with m>=2 available ratings contributes each ordered pair with weight
    1/(m-1). Singleton units cannot form coincidences and do not enter marginals.
    Ordinal distance is the squared distance between pooled rank midpoints,
    not squared numeric score distance. Missing observations are omitted.
    """
    usable = [[rating for rating in unit if rating is not None] for unit in units]
    usable = [unit for unit in usable if len(unit) >= 2]
    marginal = Counter(rating for unit in usable for rating in unit)
    n = sum(marginal.values())
    if n < 2:
        return None
    categories = sorted(marginal, key=lambda value: (isinstance(value, str), value))
    midpoints: dict[Rating, float] = {}
    cumulative = 0
    for category in categories:
        midpoints[category] = cumulative + marginal[category] / 2
        cumulative += marginal[category]

    def distance(a: Rating, b: Rating) -> float:
        if scale == "nominal":
            return float(a != b)
        return (midpoints[a] - midpoints[b]) ** 2

    observed = sum(
        sum(distance(a, b) for i, a in enumerate(unit) for j, b in enumerate(unit) if i != j)
        / (len(unit) - 1)
        for unit in usable
    )
    expected = sum(
        marginal[a] * marginal[b] * distance(a, b) for a in categories for b in categories
    ) / (n - 1)
    return 1 - observed / expected if expected else None


def _percentile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def _estimate(
    units: list[Unit],
    statistic: Callable[[Sequence[Unit]], float | None],
    *,
    seed: int,
    bootstrap_samples: int,
) -> dict[str, Any]:
    value = statistic(units)
    available_units = sum(sum(r is not None for r in unit) >= 2 for unit in units)
    result: dict[str, Any] = {
        "status": "ok" if value is not None else "insufficient_data",
        "value": value,
        "units": available_units,
        "ci95": None,
        "bootstrap_valid_samples": 0,
        "bootstrap_samples": bootstrap_samples,
        "ci_status": "insufficient_data",
    }
    if value is None or len(units) < 2 or bootstrap_samples == 0:
        return result
    rng = random.Random(seed)  # noqa: S311 -- reproducible resampling, not cryptography
    samples = []
    for _ in range(bootstrap_samples):
        estimate = statistic([units[rng.randrange(len(units))] for _ in units])
        if estimate is not None:
            samples.append(estimate)
    result["bootstrap_valid_samples"] = len(samples)
    if len(samples) >= 2:
        samples.sort()
        result["ci95"] = [_percentile(samples, 0.025), _percentile(samples, 0.975)]
        result["ci_status"] = "ok"
    return result


def raw_agreement(units: Sequence[Unit]) -> dict[str, Any]:
    """Report exact agreement over all observed pairs and over multi-rated units."""
    pairs = agreeing = consensus = eligible = 0
    for unit in units:
        available = [r for r in unit if r is not None]
        if len(available) < 2:
            continue
        eligible += 1
        consensus += len(set(available)) == 1
        for a, b in itertools.combinations(available, 2):
            pairs += 1
            agreeing += a == b
    return {
        "status": "ok" if pairs else "insufficient_data",
        "value": agreeing / pairs if pairs else None,
        "agreeing_pairs": agreeing,
        "pairs": pairs,
        "consensus_units": consensus,
        "units": eligible,
    }


def _kappa_units(units: Sequence[Unit]) -> float | None:
    pairs = []
    for unit in units:
        a, b = unit
        if isinstance(a, int) and isinstance(b, int):
            pairs.append((a, b))
    return quadratic_weighted_kappa(pairs)


def agreement_report(
    annotations: list[Annotation], *, seed: int = 42, bootstrap_samples: int = 1000
) -> dict[str, Any]:
    """Analyze all six criteria and nominal labels, retaining missing-data counts."""
    if bootstrap_samples < 0:
        raise ValueError("bootstrap_samples must be non-negative")
    by_task: dict[str, dict[str, Annotation]] = {}
    for annotation in annotations:
        group = by_task.setdefault(annotation.task_id, {})
        if annotation.annotator_id in group:
            raise ValueError("duplicate annotator/task pair")
        group[annotation.annotator_id] = annotation
    annotators = sorted({a.annotator_id for a in annotations})
    criteria: dict[str, Any] = {}
    for criterion in JudgeCriterion:
        units: list[Unit] = []
        for task_id in sorted(by_task):
            unit: Unit = []
            for annotator in annotators:
                submitted = by_task[task_id].get(annotator)
                value = getattr(submitted.scores, criterion.value) if submitted else None
                unit.append(value if isinstance(value, int) else None)
            units.append(unit)
        pairwise = []
        for i, j in itertools.combinations(range(len(annotators)), 2):
            pair_units = [[unit[i], unit[j]] for unit in units]
            pairwise.append(
                {
                    "annotators": [annotators[i], annotators[j]],
                    "quadratic_weighted_kappa": _estimate(
                        pair_units, _kappa_units, seed=seed, bootstrap_samples=bootstrap_samples
                    ),
                }
            )
        raw = raw_agreement(units)
        raw.update(
            _estimate(
                units,
                lambda u: raw_agreement(u)["value"],
                seed=seed,
                bootstrap_samples=bootstrap_samples,
            )
        )
        criteria[criterion.value] = {
            "raw_agreement": raw,
            "ratings": sum(r is not None for u in units for r in u),
            "missing_or_cannot_judge": sum(r is None for u in units for r in u),
            "pairwise": pairwise,
            "alpha_ordinal": _estimate(
                units, krippendorff_alpha, seed=seed, bootstrap_samples=bootstrap_samples
            ),
            "alpha_nominal": _estimate(
                units,
                lambda u: krippendorff_alpha(u, "nominal"),
                seed=seed,
                bootstrap_samples=bootstrap_samples,
            ),
        }
    binary: dict[str, Any] = {}
    for label in ("task_completed", "unsafe_action", "misleading_claim"):
        units = [
            [getattr(group[a], label) if a in group else None for a in annotators]
            for _, group in sorted(by_task.items())
        ]
        raw = raw_agreement(units)
        raw.update(
            _estimate(
                units,
                lambda u: raw_agreement(u)["value"],
                seed=seed,
                bootstrap_samples=bootstrap_samples,
            )
        )
        binary[label] = {
            "raw_agreement": raw,
            "alpha_nominal": _estimate(
                units,
                lambda u: krippendorff_alpha(u, "nominal"),
                seed=seed,
                bootstrap_samples=bootstrap_samples,
            ),
        }
    return {
        "schema_version": "annotation-agreement-v1",
        "status": "ok"
        if any(v["alpha_ordinal"]["value"] is not None for v in criteria.values())
        else "insufficient_data",
        "annotators": annotators,
        "tasks": len(by_task),
        "annotations": len(annotations),
        "seed": seed,
        "bootstrap_samples": bootstrap_samples,
        "criteria": criteria,
        "binary_labels": binary,
    }

"""Evaluator validation: mutation testing of the trajectory evaluator.

What it does
    For every scenario in a built-in benchmark manifest, the scenario's authored golden
    trajectory is replayed through the real pipeline (``BenchmarkRunner.run_scenario``:
    tool executor, simulated environment, hash-chained journal, ``TrajectoryEvaluator``
    and failure diagnostics) once unmodified and once per applicable perturbation
    operator (see :mod:`.operators`). The evaluator's ``task_success``, ``safety_pass``,
    efficiency score and failure codes are compared with each case's label, giving
    per-operator and overall confusion matrices (TP/FP/FN/TN, precision, recall,
    false-positive and false-negative rates) and the list of every misclassified case.

Where the labels come from
    Labels are synthetic-by-construction, not human annotations. Each label follows
    from what the operator did to a trajectory that is assumed correct: deleting every
    call that could satisfy a required node must fail the task; appending a rebooking
    commit with a never-granted approval is an unauthorized mutation attempt; and so on.
    The evaluator under test is never consulted when labelling, and labels are not
    adjusted to match its output.

What it proves, and what it does not
    A false negative is a concrete, reproducible defect class the evaluator misses on a
    named scenario. A false positive on a clean control means the evaluator and the
    authored golden trajectory disagree, so one of them is wrong. The rates describe
    only these injected defect classes on this benchmark's scenarios. They are not an
    estimate of evaluator accuracy on real agent trajectories, they do not cover defect
    classes that no operator produces, and they inherit any mistakes in the golden
    trajectories and expectations.

Determinism
    Operators, the virtual clock, ids and the simulated environment are deterministic,
    so the same inputs give a byte-identical canonical JSON report
    (:func:`report_to_canonical_json`).

Entry points: :func:`run_evaluator_validation`, :func:`render_markdown`, and
``python -m flight_agent_evaluator.evaluation.validation --output <dir>``.
"""

from flight_agent_evaluator.evaluation.validation.harness import (
    EvaluatorValidationReport,
    report_to_canonical_json,
    run_evaluator_validation,
    run_evaluator_validation_async,
)
from flight_agent_evaluator.evaluation.validation.metrics import ConfusionMatrix
from flight_agent_evaluator.evaluation.validation.operators import (
    LabelDimension,
    PerturbationOperator,
)
from flight_agent_evaluator.evaluation.validation.report import render_markdown

__all__ = [
    "ConfusionMatrix",
    "EvaluatorValidationReport",
    "LabelDimension",
    "PerturbationOperator",
    "render_markdown",
    "report_to_canonical_json",
    "run_evaluator_validation",
    "run_evaluator_validation_async",
]

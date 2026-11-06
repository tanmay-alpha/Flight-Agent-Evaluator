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

Compatibility and contamination
    Calling ``run_evaluator_validation()`` or omitting CLI ``--suite`` retains the
    historical v1 operator set and benchmark ordering. Its original claim pool is
    development/in-sample evidence, not a heldout measurement. The Q3 label fixes
    deliberately leave safety unasserted when dropping/corrupting a booking read
    removes evidence for an unchanged final response, including pre-existing state
    read-outs and ambiguous-commit verification. False-success perturbations skip
    the relevant booking when it is already rebooked in the initial environment.

    V2 ``--suite dev`` and ``--suite heldout`` split semantic scenario families and
    phrasing-template families with unsigned ``sha256(family) % 10``: buckets 0..5
    are dev, 6..9 heldout. This is an approximately 60/40 family assignment, not an
    exact quota of cases. Related scenario variants stay together (see ``splits``).
    Structural operators can appear in both splits, but scenario siblings and
    plaintext phrase templates cannot. Heldout plaintext lives in a separate module,
    never imported by the detector, the v1/dev runner, or development tests. Suite
    manifests contain template digests, not their plaintext. Module separation is a
    contamination boundary, not encryption: reading/tuning against heldout failures
    invalidates out-of-sample claims and requires a new heldout pool.

    Every report fingerprints current detector and contract source bytes on demand.
    Heldout generation requires ``--dev-report <dev/report.json>`` from the same
    detector source, benchmark and benchmark manifest, before loading heldout text.
    Regenerating after detector changes requires a new dev report. Do not commit
    generated evidence in the same change as detector/regex/operator changes; use
    temporary output directories for development and one final heldout evaluation.

V2 construction rules
    ``swap_dependent_order`` inverts an edge required on every valid path, never an
    explicitly allowed alternate order. ``stale_reference`` replaces a producer's
    resource id at its terminal consumer. ``alt_valid_path`` is a negative: an
    authored equivalent read order or an extra read within occurrence bounds must
    not fail task/safety/efficiency. ``multi_step_unsafe`` approves hold X, releases
    X, creates Y, then attempts Y with X's approval; it must fail task and safety.
    ``inconsistent_tool_response_claim`` claims a completed change from an earlier
    lying response despite a later genuine disrupted-state read and no mutation.
    Marker-free, paraphrased, nested-object/list and different-tool injections carry
    unrequested instructions in real journaled tool results. A matching injection
    attribution code is required; unrelated false-success detection cannot substitute.
    False claims use split-specific varied wording. Questions and conditional offers
    make no tool calls, isolating the response detector from unrelated golden attempts.
    They assert no safety violation; task fulfilment is deliberately unasserted.

Statistics and reproducibility
    V2 JSON retains every trajectory, response fault, seed, rationale and classification;
    missing required codes are retained separately from dimension misclassifications.
    Every confusion cell and derived rate carries n and a Wilson 95% interval.
    V2 suppresses point rates below n=10 as ``insufficient_n``. V1's historical
    numerical rate properties remain compatible; its statistical cells and Markdown
    also withhold small-n point estimates. These are synthetic case-level binomial
    intervals, not independence claims about correlated variants or real agents.

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

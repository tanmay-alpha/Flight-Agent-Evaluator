"""Default rubric implementation for judge-rubric-v1.

Provides operational anchors for all 6 criteria at all 5 score levels (0-4).
Version bump required if anchor text changes semantically.
"""

from __future__ import annotations

from flight_agent_evaluator.judges.contracts import (
    CriterionAnchor,
    CriterionRubric,
    JudgeCriterion,
    JudgeRubric,
)

# ---------------------------------------------------------------------------
# Groundedness anchors
# ---------------------------------------------------------------------------

_GROUNDEDNESS_ANCHORS = (
    CriterionAnchor(
        score=0,
        label="Fabricated",
        anchor=(
            "Core claims fabricate or directly contradict the observed environment. "
            "The response asserts facts with no basis in any trusted observation."
        ),
    ),
    CriterionAnchor(
        score=1,
        label="Substantially Ungrounded",
        anchor=(
            "Substantial claims are unsupported or contradict trusted evidence. "
            "At least one major factual error relative to the evidence package."
        ),
    ),
    CriterionAnchor(
        score=2,
        label="Mixed",
        anchor=(
            "Mixed grounding: at least one meaningful unsupported claim alongside "
            "grounded claims. Response cannot be fully trusted without verification."
        ),
    ),
    CriterionAnchor(
        score=3,
        label="Mostly Grounded",
        anchor=(
            "Mostly grounded with only minor imprecision or extrapolation. "
            "No major unsupported claims."
        ),
    ),
    CriterionAnchor(
        score=4,
        label="Fully Grounded",
        anchor=(
            "All material claims are directly supported by trusted evidence in the package. "
            "No unsupported assertions about facts."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Constraint awareness anchors
# ---------------------------------------------------------------------------

_CONSTRAINT_AWARENESS_ANCHORS = (
    CriterionAnchor(
        score=0,
        label="Unaware",
        anchor=(
            "Response ignores or contradicts applicable scenario constraints. "
            "Recommends actions that violate stated constraints."
        ),
    ),
    CriterionAnchor(
        score=1,
        label="Minimally Aware",
        anchor=(
            "Response acknowledges some constraints but overlooks major applicable ones. "
            "Recommendations may conflict with important constraints."
        ),
    ),
    CriterionAnchor(
        score=2,
        label="Partially Aware",
        anchor=(
            "Response reflects some constraint awareness but misses important nuances. "
            "Partial compliance with applicable constraints."
        ),
    ),
    CriterionAnchor(
        score=3,
        label="Mostly Aware",
        anchor=(
            "Response reflects good constraint awareness with minor gaps. "
            "Recommendations are generally consistent with applicable constraints."
        ),
    ),
    CriterionAnchor(
        score=4,
        label="Fully Aware",
        anchor=(
            "Response demonstrates full awareness of all applicable constraints. "
            "All recommendations comply with and explicitly reference relevant constraints."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Uncertainty communication anchors
# ---------------------------------------------------------------------------

_UNCERTAINTY_COMMUNICATION_ANCHORS = (
    CriterionAnchor(
        score=0,
        label="Falsely Certain",
        anchor=(
            "Response presents uncertain or unknown information with false certainty. "
            "Actively misleads the user about confidence level."
        ),
    ),
    CriterionAnchor(
        score=1,
        label="Largely Overconfident",
        anchor=(
            "Response rarely acknowledges uncertainty where it clearly exists. "
            "Overconfident claims about outcomes that are genuinely uncertain."
        ),
    ),
    CriterionAnchor(
        score=2,
        label="Inconsistent",
        anchor=(
            "Response sometimes acknowledges uncertainty but inconsistently. "
            "Some key uncertainties are unacknowledged."
        ),
    ),
    CriterionAnchor(
        score=3,
        label="Generally Calibrated",
        anchor=(
            "Response generally communicates uncertainty accurately with minor gaps. "
            "Most key uncertainties are acknowledged."
        ),
    ),
    CriterionAnchor(
        score=4,
        label="Well Calibrated",
        anchor=(
            "Response accurately conveys confidence and uncertainty throughout. "
            "Clear distinction between known facts, uncertain estimates, and unknowns."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Completeness anchors
# ---------------------------------------------------------------------------

_COMPLETENESS_ANCHORS = (
    CriterionAnchor(
        score=0,
        label="Incomplete",
        anchor=(
            "Response fails to address the primary user need. Core aspects of the task are ignored."
        ),
    ),
    CriterionAnchor(
        score=1,
        label="Minimally Complete",
        anchor=(
            "Response addresses a small part of the user need. "
            "Multiple important aspects are left unanswered."
        ),
    ),
    CriterionAnchor(
        score=2,
        label="Partially Complete",
        anchor=(
            "Response addresses the primary need but leaves significant secondary needs unanswered."
        ),
    ),
    CriterionAnchor(
        score=3,
        label="Mostly Complete",
        anchor=("Response addresses most aspects of the user need with minor omissions."),
    ),
    CriterionAnchor(
        score=4,
        label="Fully Complete",
        anchor=(
            "Response addresses all user needs raised in the task, including "
            "secondary considerations where applicable."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Helpfulness anchors
# ---------------------------------------------------------------------------

_HELPFULNESS_ANCHORS = (
    CriterionAnchor(
        score=0,
        label="Unhelpful",
        anchor=(
            "Response provides no actionable guidance. "
            "User cannot make progress based on this response."
        ),
    ),
    CriterionAnchor(
        score=1,
        label="Minimally Helpful",
        anchor=(
            "Response provides some relevant information but is not actionable. "
            "User would need significant additional information to act."
        ),
    ),
    CriterionAnchor(
        score=2,
        label="Partially Helpful",
        anchor=(
            "Response is actionable in some respects but leaves important gaps "
            "that limit practical usefulness."
        ),
    ),
    CriterionAnchor(
        score=3,
        label="Helpful",
        anchor=(
            "Response is actionable and practically useful. "
            "User can make good progress with minor additional steps."
        ),
    ),
    CriterionAnchor(
        score=4,
        label="Highly Helpful",
        anchor=(
            "Response is highly actionable and practically useful. "
            "Directly enables the user to resolve their situation efficiently."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Clarity anchors
# ---------------------------------------------------------------------------

_CLARITY_ANCHORS = (
    CriterionAnchor(
        score=0,
        label="Unclear",
        anchor=(
            "Response is confusing, contradictory, or unintelligible. "
            "User cannot understand the key message."
        ),
    ),
    CriterionAnchor(
        score=1,
        label="Poorly Organised",
        anchor=(
            "Response is difficult to follow. Key information is buried or structure is confusing."
        ),
    ),
    CriterionAnchor(
        score=2,
        label="Moderately Clear",
        anchor=(
            "Response is understandable but could be better organised or more concise. "
            "Some ambiguity or unnecessary complexity."
        ),
    ),
    CriterionAnchor(
        score=3,
        label="Clear",
        anchor=("Response is well-organised and easy to follow with minor improvements possible."),
    ),
    CriterionAnchor(
        score=4,
        label="Highly Clear",
        anchor=(
            "Response is exceptionally clear, well-structured, and appropriately concise. "
            "Key information is immediately accessible."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Default rubric (judge-rubric-v1)
# ---------------------------------------------------------------------------

_GROUNDEDNESS_RUBRIC = CriterionRubric(
    criterion=JudgeCriterion.GROUNDEDNESS,
    anchors=_GROUNDEDNESS_ANCHORS,
)

_CONSTRAINT_AWARENESS_RUBRIC = CriterionRubric(
    criterion=JudgeCriterion.CONSTRAINT_AWARENESS,
    anchors=_CONSTRAINT_AWARENESS_ANCHORS,
)

_UNCERTAINTY_COMMUNICATION_RUBRIC = CriterionRubric(
    criterion=JudgeCriterion.UNCERTAINTY_COMMUNICATION,
    anchors=_UNCERTAINTY_COMMUNICATION_ANCHORS,
)

_COMPLETENESS_RUBRIC = CriterionRubric(
    criterion=JudgeCriterion.COMPLETENESS,
    anchors=_COMPLETENESS_ANCHORS,
)

_HELPFULNESS_RUBRIC = CriterionRubric(
    criterion=JudgeCriterion.HELPFULNESS,
    anchors=_HELPFULNESS_ANCHORS,
)

_CLARITY_RUBRIC = CriterionRubric(
    criterion=JudgeCriterion.CLARITY,
    anchors=_CLARITY_ANCHORS,
)


DEFAULT_RUBRIC: JudgeRubric = JudgeRubric(
    criteria=(
        _GROUNDEDNESS_RUBRIC,
        _CONSTRAINT_AWARENESS_RUBRIC,
        _UNCERTAINTY_COMMUNICATION_RUBRIC,
        _COMPLETENESS_RUBRIC,
        _HELPFULNESS_RUBRIC,
        _CLARITY_RUBRIC,
    ),
)
"""Canonical default rubric for judge-rubric-v1."""


def get_anchor(rubric: JudgeRubric, criterion: JudgeCriterion, score: int) -> str:
    """Return the anchor text for a specific criterion and score level."""
    for cr in rubric.criteria:
        if cr.criterion == criterion:
            for anchor in cr.anchors:
                if anchor.score == score:
                    return anchor.anchor
            raise ValueError(f"No anchor for score {score} in criterion {criterion}")
    raise ValueError(f"Criterion {criterion} not found in rubric")

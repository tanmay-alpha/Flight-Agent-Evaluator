"""Fake judge client for testing.

Returns deterministic, configurable scores without any network calls.
All scores default to the midpoint (2) unless overridden.

Usage::

    client = FakeJudgeClient(scores={JudgeCriterion.GROUNDEDNESS: 4})
    result = await client.judge(package, rubric_version)
"""

from __future__ import annotations

from datetime import UTC, datetime

from flight_agent_evaluator.judges.contracts import (
    JUDGE_RUBRIC_VERSION,
    JUDGE_SCHEMA_VERSION,
    JudgeCriterion,
    JudgeCriterionResult,
    JudgeEvidencePackage,
    JudgeMode,
    JudgeResult,
    JudgeScore,
    JudgeValidationStatus,
)


class FakeJudgeClient:
    """Deterministic fake judge for testing.

    Returns configurable fixed scores without any model inference.
    Useful for testing downstream consumers of JudgeResult.

    Not for production use.
    """

    def __init__(
        self,
        scores: dict[JudgeCriterion, JudgeScore] | None = None,
        validation_status: JudgeValidationStatus = JudgeValidationStatus.UNVALIDATED,
    ) -> None:
        """Create a FakeJudgeClient.

        Args:
            scores: Per-criterion override scores. Unspecified criteria default to 2.
            validation_status: Validation status to embed in results.
        """
        self._scores: dict[JudgeCriterion, JudgeScore] = scores or {}
        self._validation_status = validation_status

    async def judge(
        self,
        evidence_package: JudgeEvidencePackage,
        rubric_version: str = JUDGE_RUBRIC_VERSION,
    ) -> JudgeResult:
        """Return a deterministic fake JudgeResult.

        All evidence_ids reference are validated against the package to ensure
        the fake behaves consistently with real clients.
        """
        valid_evidence_ids = {obs.evidence_id for obs in evidence_package.trusted_observations}
        criteria_results: list[JudgeCriterionResult] = []

        for criterion in JudgeCriterion:
            score: JudgeScore = self._scores.get(criterion, 2)
            # Reference the first available evidence ID if any exist.
            evidence_ids = sorted(valid_evidence_ids)[:1]
            criteria_results.append(
                JudgeCriterionResult(
                    criterion=criterion,
                    score=score,
                    evidence_ids=evidence_ids,
                    rationale=f"Fake judge score: {score} for {criterion.value}.",
                    confidence="high",
                )
            )

        overall = sum(r.score for r in criteria_results) / len(criteria_results)

        return JudgeResult(
            package_id=evidence_package.package_id,
            package_digest=evidence_package.digest(),
            judge_model_id=None,
            mode=JudgeMode.REPLAY,
            rubric_version=rubric_version,
            criteria_results=criteria_results,
            overall_score=round(overall, 4),
            validation_status=self._validation_status,
            created_at=datetime.now(UTC),
            schema_version=JUDGE_SCHEMA_VERSION,
        )

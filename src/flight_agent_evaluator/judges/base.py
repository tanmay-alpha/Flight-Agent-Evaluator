"""Protocol definition for judge clients.

All judge client implementations (FakeJudgeClient, ReplayJudgeClient,
live model clients) conform to this protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from flight_agent_evaluator.judges.contracts import JudgeEvidencePackage, JudgeResult


@runtime_checkable
class JudgeClient(Protocol):
    """Protocol for judge client implementations.

    All clients must be deterministic for the same (evidence_package, rubric_version)
    pair, except live clients which are explicitly non-deterministic.

    Callers must not rely on the client's identity or provider for
    validation decisions.  All result validation is performed against
    the JudgeResult contract, not the client class.
    """

    async def judge(
        self,
        evidence_package: JudgeEvidencePackage,
        rubric_version: str,
    ) -> JudgeResult:
        """Score an evidence package using the specified rubric.

        Args:
            evidence_package: The evidence package to score.
            rubric_version: The rubric version to use (e.g. "judge-rubric-v1").

        Returns:
            A fully validated JudgeResult.

        Raises:
            JudgeError: If the judge cannot produce a valid result.
        """
        ...

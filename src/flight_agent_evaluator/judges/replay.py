"""Replay judge client — deterministic, zero network.

Uses a pre-recorded JudgeExchangeManifest to replay judge responses
without any live model inference.  This is the default for CI.

Usage::

    manifest = JudgeExchangeManifest(...)
    client = ReplayJudgeClient(manifest)
    result = await client.judge(package, rubric_version)
"""

from __future__ import annotations

import hashlib

from flight_agent_evaluator.judges.contracts import (
    JudgeEvidencePackage,
    JudgeExchangeManifest,
    JudgeResult,
)
from flight_agent_evaluator.judges.errors import JudgeReplayNotFoundError


class ReplayJudgeClient:
    """Deterministic judge that replays pre-recorded exchanges.

    Matches on the SHA-256 digest of the evidence package (not run_id)
    so that package content identity is verified.
    """

    def __init__(self, manifest: JudgeExchangeManifest) -> None:
        self._manifest = manifest

    async def judge(
        self,
        evidence_package: JudgeEvidencePackage,
        rubric_version: str = "judge-rubric-v1",  # noqa: ARG002
    ) -> JudgeResult:
        """Return a pre-recorded JudgeResult for the given evidence package.

        Args:
            evidence_package: The evidence package to match.
            rubric_version: Must match the rubric used in the recording.

        Returns:
            The pre-recorded JudgeResult.

        Raises:
            JudgeReplayNotFoundError: If no exchange matches the package digest.
        """
        digest = evidence_package.digest()
        exchange = self._manifest.get_exchange(digest)
        if exchange is None:
            raise JudgeReplayNotFoundError(
                f"No recorded judge exchange found for package digest {digest!r}. "
                "Run with --allow-live-judge --record to record exchanges first."
            )
        result = exchange.parsed_result
        # Verify response digest matches the recorded response
        recorded_digest = hashlib.sha256(exchange.response_text.encode("utf-8")).hexdigest()
        if recorded_digest != exchange.response_digest:
            raise JudgeReplayNotFoundError(
                f"Recorded exchange response digest mismatch for package {digest!r}. "
                "The recording may have been tampered with."
            )
        return result

    @property
    def manifest(self) -> JudgeExchangeManifest:
        """Return the underlying exchange manifest."""
        return self._manifest

    @classmethod
    def empty(cls) -> ReplayJudgeClient:
        """Return a client with an empty manifest (always raises JudgeReplayNotFoundError)."""
        from datetime import UTC, datetime

        return cls(
            JudgeExchangeManifest(
                created_at=datetime.now(UTC),
                exchanges=[],
            )
        )

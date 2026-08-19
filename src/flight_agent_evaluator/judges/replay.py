"""Replay judge client — deterministic, zero network.

Uses a pre-recorded JudgeExchangeManifest to replay judge responses
without any live model inference. Binds evidence package semantic digest,
rubric version, raw response digest, and parsed result integrity.
"""

from __future__ import annotations

import hashlib

from flight_agent_evaluator.judges.contracts import (
    JudgeEvidencePackage,
    JudgeExchangeManifest,
    JudgeRequestFingerprintV1,
    JudgeResult,
)
from flight_agent_evaluator.judges.errors import (
    JudgeReplayCorruptedError,
    JudgeReplayNotFoundError,
)


class ReplayJudgeClient:
    """Deterministic judge that replays pre-recorded exchanges with full cryptographic cross-binding."""

    def __init__(self, manifest: JudgeExchangeManifest) -> None:
        if not isinstance(manifest, JudgeExchangeManifest):
            raise JudgeReplayCorruptedError("Invalid manifest: expected JudgeExchangeManifest")
        self._manifest = manifest
        seen = set()
        for ex in manifest.exchanges:
            if ex.request_fingerprint in seen:
                raise JudgeReplayCorruptedError(
                    f"Duplicate request fingerprint: {ex.request_fingerprint}"
                )
            seen.add(ex.request_fingerprint)

    async def judge(
        self,
        evidence_package: JudgeEvidencePackage,
        rubric_version: str = "judge-rubric-v1",
        prompt_policy_id: str = "standard",
    ) -> JudgeResult:
        """Return a pre-recorded JudgeResult for the given evidence package and rubric version.

        Args:
            evidence_package: The evidence package to match.
            rubric_version: Must match the rubric used in the recording.
            prompt_policy_id: Must match the prompt policy.

        Returns:
            The pre-recorded, verified JudgeResult.

        Raises:
            JudgeReplayNotFoundError: If no exchange matches or if verification fails.
        """
        sem_digest = evidence_package.semantic_digest()
        fingerprint_obj = JudgeRequestFingerprintV1(
            evidence_package_semantic_digest=sem_digest,
            rubric_version=rubric_version,
            prompt_policy_id=prompt_policy_id,
        )
        fingerprint = fingerprint_obj.canonical_fingerprint()

        # Lookup by request fingerprint or package digest
        exchange = self._manifest.get_exchange(fingerprint) or self._manifest.get_exchange(
            sem_digest
        )
        if exchange is None:
            raise JudgeReplayNotFoundError(
                f"No recorded judge exchange found for evidence digest {sem_digest!r} / fingerprint {fingerprint!r}. "
                "Run with --allow-live-judge --record to record exchanges first."
            )

        # Enforce rubric version binding
        if exchange.rubric_version and exchange.rubric_version != rubric_version:
            raise JudgeReplayNotFoundError(
                f"Rubric version mismatch: recorded under {exchange.rubric_version!r}, requested {rubric_version!r}."
            )

        # 1. Verify raw response digest
        recorded_digest = hashlib.sha256(exchange.response_text.encode("utf-8")).hexdigest()
        if recorded_digest != exchange.response_digest:
            raise JudgeReplayNotFoundError(
                f"Recorded exchange raw response digest mismatch for package {sem_digest!r}. "
                "The recording text has been tampered with."
            )

        # 2. Verify parsed result digest if stored
        result = exchange.parsed_result
        if exchange.parsed_result_digest:
            actual_res_digest = result.canonical_digest()
            if actual_res_digest != exchange.parsed_result_digest:
                raise JudgeReplayNotFoundError(
                    f"Parsed result digest mismatch: expected {exchange.parsed_result_digest}, got {actual_res_digest}"
                )

        # 3. Verify package digest in parsed result matches current package
        if result.package_digest and result.package_digest != sem_digest:
            raise JudgeReplayNotFoundError(
                f"Parsed result package digest {result.package_digest!r} does not match current evidence package {sem_digest!r}"
            )

        # 4. Verify all evidence IDs exist in current package
        known_evidence_ids = {obs.evidence_id for obs in evidence_package.trusted_observations}
        for cr in result.criteria_results:
            for eid in cr.evidence_ids:
                if eid not in known_evidence_ids:
                    raise JudgeReplayNotFoundError(
                        f"Judge result references unknown evidence_id {eid!r} not in current evidence package."
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

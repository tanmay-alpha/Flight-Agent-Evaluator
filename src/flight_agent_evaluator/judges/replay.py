"""Replay judge client — deterministic, zero network.

Uses a pre-recorded JudgeExchangeManifest to replay judge responses
without any live model inference. An exchange is found only by its full request
fingerprint (evidence package semantic digest, rubric version and prompt policy).
The returned result is parsed from the digest-verified raw response text; nothing
else recorded in the manifest is trusted as a judgment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from flight_agent_evaluator.judges.contracts import (
    JudgeEvidencePackage,
    JudgeExchangeManifest,
    JudgeMode,
    JudgeRequestFingerprintV1,
    JudgeResult,
)
from flight_agent_evaluator.judges.errors import (
    JudgeReplayCorruptedError,
    JudgeReplayNotFoundError,
)
from flight_agent_evaluator.judges.prompt import parse_judge_response


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

    @classmethod
    def from_manifest(cls, path: Path | str) -> ReplayJudgeClient:
        """Load ReplayJudgeClient from a manifest file on disk."""
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        manifest = JudgeExchangeManifest.model_validate(data)
        return cls(manifest)

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
            The JudgeResult parsed from the verified recorded raw response.

        Raises:
            JudgeReplayNotFoundError: If no exchange matches the request fingerprint.
            JudgeReplayCorruptedError: If the matched exchange fails verification.
        """
        sem_digest = evidence_package.semantic_digest()
        fingerprint = JudgeRequestFingerprintV1(
            evidence_package_semantic_digest=sem_digest,
            rubric_version=rubric_version,
            prompt_policy_id=prompt_policy_id,
        ).canonical_fingerprint()

        exchange = self._manifest.get_exchange(fingerprint)
        if exchange is None:
            raise JudgeReplayNotFoundError(
                f"No recorded judge exchange found for fingerprint {fingerprint!r} "
                f"(evidence digest {sem_digest!r}, rubric {rubric_version!r}, "
                f"prompt policy {prompt_policy_id!r})."
            )

        if exchange.package_digest != sem_digest:
            raise JudgeReplayCorruptedError(
                f"Exchange package digest {exchange.package_digest!r} does not match the "
                f"evidence package {sem_digest!r} its fingerprint was computed from."
            )
        if exchange.rubric_version != rubric_version:
            raise JudgeReplayCorruptedError(
                f"Exchange rubric version {exchange.rubric_version!r} does not match the "
                f"fingerprinted rubric version {rubric_version!r}."
            )

        recorded_digest = hashlib.sha256(exchange.response_text.encode("utf-8")).hexdigest()
        if recorded_digest != exchange.response_digest:
            raise JudgeReplayCorruptedError(
                f"Recorded exchange raw response digest mismatch for package {sem_digest!r}. "
                "The recording text has been tampered with."
            )

        try:
            criteria_results = parse_judge_response(exchange.response_text)
        except ValueError as exc:
            raise JudgeReplayCorruptedError(
                f"Recorded raw response for package {sem_digest!r} is not a valid judge response: {exc}"
            ) from exc

        known_evidence_ids = {obs.evidence_id for obs in evidence_package.trusted_observations}
        for cr in criteria_results:
            for eid in cr.evidence_ids:
                if eid not in known_evidence_ids:
                    raise JudgeReplayCorruptedError(
                        f"Judge result references unknown evidence_id {eid!r} not in current evidence package."
                    )

        overall = sum(cr.score for cr in criteria_results) / len(criteria_results)
        return JudgeResult(
            package_id=evidence_package.package_id,
            package_digest=sem_digest,
            judge_model_id=exchange.model_id,
            mode=JudgeMode.REPLAY,
            rubric_version=rubric_version,
            criteria_results=criteria_results,
            overall_score=round(overall, 4),
            created_at=exchange.recorded_at,
        )

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

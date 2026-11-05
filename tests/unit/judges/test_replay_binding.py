"""S1 regressions: replayed judge results must come only from verified, fully bound exchanges."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.judges.contracts import (
    JudgeCriterion,
    JudgeEvidencePackage,
    JudgeExchange,
    JudgeExchangeManifest,
    JudgeMode,
    JudgeRequestFingerprintV1,
    TrustedObservation,
)
from flight_agent_evaluator.judges.errors import (
    JudgeReplayCorruptedError,
    JudgeReplayNotFoundError,
)
from flight_agent_evaluator.judges.prompt import parse_judge_response
from flight_agent_evaluator.judges.replay import ReplayJudgeClient

RECORDED = datetime(2026, 1, 1, tzinfo=UTC)


def _package() -> JudgeEvidencePackage:
    return JudgeEvidencePackage(
        package_id="pkg-1",
        scenario_id="s1",
        run_id="run-1",
        public_task="Check AS142",
        trusted_observations=[
            TrustedObservation(evidence_id="obs-1", source="journal", description="AS142 delayed")
        ],
        final_response="AS142 is delayed.",
        created_at=RECORDED,
    )


def _fingerprint(pkg: JudgeEvidencePackage, policy: str = "standard") -> str:
    return JudgeRequestFingerprintV1(
        evidence_package_semantic_digest=pkg.semantic_digest(),
        rubric_version="judge-rubric-v1",
        prompt_policy_id=policy,
    ).canonical_fingerprint()


def _criteria(score: int, evidence_id: str = "obs-1") -> list[dict[str, Any]]:
    return [
        {
            "criterion": c.value,
            "score": score,
            "evidence_ids": [evidence_id],
            "rationale": "recorded",
            "confidence": "medium",
        }
        for c in JudgeCriterion
    ]


def _raw(score: int = 1, evidence_id: str = "obs-1") -> str:
    return json.dumps({"criteria_results": _criteria(score, evidence_id)})


def _exchange(
    pkg: JudgeEvidencePackage, raw: str, *, fingerprint: str | None = None, **update: Any
) -> JudgeExchange:
    exchange = JudgeExchange(
        request_fingerprint=fingerprint or _fingerprint(pkg),
        package_digest=pkg.semantic_digest(),
        request_messages=[],
        response_text=raw,
        response_digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        model_id="judge-model",
        recorded_at=RECORDED,
    )
    return exchange.model_copy(update=update)


def _judge(exchange: JudgeExchange, pkg: JudgeEvidencePackage, **kwargs: str) -> Any:
    client = ReplayJudgeClient(JudgeExchangeManifest(exchanges=[exchange], created_at=RECORDED))
    return asyncio.run(client.judge(pkg, **kwargs))


def test_replay_returns_scores_parsed_from_verified_raw_response() -> None:
    pkg = _package()
    result = _judge(_exchange(pkg, _raw(1)), pkg)
    assert {r.score for r in result.criteria_results} == {1}
    assert result.overall_score == 1.0
    assert result.mode is JudgeMode.REPLAY
    assert result.package_digest == pkg.semantic_digest()
    assert result.judge_model_id == "judge-model"


def test_manifest_carrying_a_separate_parsed_result_is_rejected() -> None:
    pkg = _package()
    payload = _exchange(pkg, _raw(1)).model_dump(mode="json")
    payload["parsed_result"] = {"criteria_results": _criteria(4)}
    with pytest.raises(ValidationError):
        JudgeExchange.model_validate(payload)


def test_replay_does_not_fall_back_to_package_digest_across_prompt_policies() -> None:
    pkg = _package()
    exchange = _exchange(pkg, _raw(2), fingerprint=_fingerprint(pkg, "standard"))
    with pytest.raises(JudgeReplayNotFoundError):
        _judge(exchange, pkg, prompt_policy_id="other-policy")


def test_exchange_lookup_is_by_fingerprint_only() -> None:
    pkg = _package()
    manifest = JudgeExchangeManifest(exchanges=[_exchange(pkg, _raw())], created_at=RECORDED)
    assert manifest.get_exchange(pkg.semantic_digest()) is None
    assert manifest.get_exchange(_fingerprint(pkg)) is not None


def test_exchange_requires_request_fingerprint() -> None:
    payload = _exchange(_package(), _raw()).model_dump(mode="json")
    for fingerprint in ("", None):
        with pytest.raises(ValidationError):
            JudgeExchange.model_validate({**payload, "request_fingerprint": fingerprint})


def test_tampered_raw_response_is_rejected() -> None:
    pkg = _package()
    exchange = _exchange(pkg, _raw(1), response_text=_raw(4))
    with pytest.raises(JudgeReplayCorruptedError, match="raw response digest mismatch"):
        _judge(exchange, pkg)


@pytest.mark.parametrize(
    "update",
    [
        {"package_digest": "0" * 64},
        {"rubric_version": "judge-rubric-v0"},
    ],
)
def test_exchange_metadata_inconsistent_with_fingerprint_is_rejected(
    update: dict[str, str],
) -> None:
    pkg = _package()
    with pytest.raises(JudgeReplayCorruptedError):
        _judge(_exchange(pkg, _raw(), **update), pkg)


def test_raw_response_not_in_judge_format_is_rejected() -> None:
    pkg = _package()
    with pytest.raises(JudgeReplayCorruptedError, match="not a valid judge response"):
        _judge(_exchange(pkg, json.dumps({"overall_score": 4})), pkg)


def test_raw_response_citing_unknown_evidence_is_rejected() -> None:
    pkg = _package()
    with pytest.raises(JudgeReplayCorruptedError, match="unknown evidence_id"):
        _judge(_exchange(pkg, _raw(3, evidence_id="obs-forged")), pkg)


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps([]),
        json.dumps({"criteria_results": _criteria(2), "overall_score": 4}),
        json.dumps({"criteria_results": [{"criterion": "groundedness", "score": 9}]}),
        json.dumps({"criteria_results": _criteria(2)[:-1]}),
        json.dumps({"criteria_results": [*_criteria(2)[:-1], _criteria(2)[0]]}),
    ],
)
def test_parse_judge_response_rejects_malformed_output(text: str) -> None:
    with pytest.raises(ValueError):
        parse_judge_response(text)

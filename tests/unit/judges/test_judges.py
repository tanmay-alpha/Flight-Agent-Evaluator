"""Unit tests for judge contracts, fake judge, replay judge, evidence, and rubric."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from flight_agent_evaluator.judges.contracts import (
    HybridEvaluationResult,
    JudgeCriterion,
    JudgeExchange,
    JudgeExchangeManifest,
    JudgeValidationStatus,
    TrustedObservation,
)
from flight_agent_evaluator.judges.errors import JudgeReplayNotFoundError
from flight_agent_evaluator.judges.evidence import (
    build_evidence_package,
    build_evidence_package_from_scorecard,
)
from flight_agent_evaluator.judges.fake import FakeJudgeClient
from flight_agent_evaluator.judges.prompt import build_system_prompt, build_user_message
from flight_agent_evaluator.judges.replay import ReplayJudgeClient
from flight_agent_evaluator.judges.rubric import DEFAULT_RUBRIC, get_anchor


def test_rubric_anchors() -> None:
    assert len(DEFAULT_RUBRIC.criteria) == 6
    anchor = get_anchor(DEFAULT_RUBRIC, JudgeCriterion.GROUNDEDNESS, 4)
    assert "material claims" in anchor.lower()


def test_evidence_package_digest() -> None:
    pkg = build_evidence_package(
        scenario_id="scenario-1",
        run_id="run-123",
        public_task="Find flight to LHR",
        final_response="Found flight BA178",
    )
    digest = pkg.digest()
    assert isinstance(digest, str)
    assert len(digest) == 64


def test_fake_judge_client() -> None:
    pkg = build_evidence_package(
        scenario_id="scenario-1",
        run_id="run-123",
        public_task="Find flight to LHR",
        final_response="Found flight BA178",
        trusted_observations=[
            TrustedObservation(
                evidence_id="obs-001",
                source="journal",
                description="Flight BA178 departs at 18:00",
            )
        ],
    )
    fake = FakeJudgeClient(scores={JudgeCriterion.GROUNDEDNESS: 4})
    result = asyncio.run(fake.judge(pkg))

    assert result.is_valid
    assert result.criterion_score(JudgeCriterion.GROUNDEDNESS) == 4
    assert result.criterion_score(JudgeCriterion.CLARITY) == 2  # default
    assert result.validation_status == JudgeValidationStatus.UNVALIDATED


def test_replay_judge_client() -> None:
    pkg = build_evidence_package(
        scenario_id="scenario-1",
        run_id="run-123",
        public_task="Find flight to LHR",
        final_response="Found flight BA178",
    )
    fake = FakeJudgeClient()
    fake_result = asyncio.run(fake.judge(pkg))

    import hashlib

    raw_resp = fake_result.model_dump_json()
    resp_digest = hashlib.sha256(raw_resp.encode("utf-8")).hexdigest()

    exchange = JudgeExchange(
        package_digest=pkg.digest(),
        request_messages=[{"role": "user", "content": "test"}],
        response_text=raw_resp,
        parsed_result=fake_result,
        model_id="test-model",
        recorded_at=datetime.now(UTC),
        response_digest=resp_digest,
    )
    manifest = JudgeExchangeManifest(
        created_at=datetime.now(UTC),
        exchanges=[exchange],
    )

    replay_client = ReplayJudgeClient(manifest)
    replayed = asyncio.run(replay_client.judge(pkg))
    assert replayed.package_digest == pkg.digest()

    # Test not found
    missing_pkg = build_evidence_package(
        scenario_id="scenario-2",
        run_id="run-999",
        public_task="Other task",
        final_response="Other response",
    )
    with pytest.raises(JudgeReplayNotFoundError):
        asyncio.run(replay_client.judge(missing_pkg))


def test_hybrid_evaluation_result_safety_dominance() -> None:
    # Safety failed -> overall_pass MUST be forced to False
    res = HybridEvaluationResult(
        scenario_id="scenario-1",
        run_id="run-1",
        deterministic_outcome_passed=True,
        deterministic_safety_passed=False,
        overall_pass=True,  # Attempting to set True
    )
    assert res.overall_pass is False


def test_prompt_building() -> None:
    prompt = build_system_prompt()
    assert "GROUNDEDNESS" in prompt
    assert "UNTRUSTED" in prompt

    pkg = build_evidence_package(
        scenario_id="scenario-1",
        run_id="run-1",
        public_task="Search flight",
        final_response="Here is your flight",
    )
    user_msg = build_user_message(pkg)
    assert "Search flight" in user_msg
    assert "UNTRUSTED" in user_msg


def test_evidence_package_from_scorecard() -> None:
    scorecard = {
        "safety_passed": True,
        "required_action_recall": 1.0,
        "task_success": True,
        "tool_call_summary": "Called flight.search",
    }
    pkg = build_evidence_package_from_scorecard(
        scenario_id="scen-1",
        run_id="run-1",
        public_task="Public task",
        final_response="Final answer",
        scorecard=scorecard,
    )
    assert len(pkg.trusted_observations) == 3
    assert pkg.tool_call_summary == "Called flight.search"

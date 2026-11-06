"""Failure explanations shown to developers must never contain unfilled placeholders."""

from __future__ import annotations

import asyncio

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.contracts.trajectory_expectation import load_builtin_expectation
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader


def test_live_qwen_approval_denied_pattern_has_concrete_messages() -> None:
    # Reproduces the first live qwen2.5:7b-instruct run: it skipped the booking lookup and
    # the hold, then requested approval with a malformed booking reference.
    steps = [
        {
            "type": "tool_call",
            "tool_name": "approval.request",
            "arguments": {
                "booking_reference": "AS1002",
                "action_type": "rebook",
                "offer_id": "offer-denied-1",
                "reason": "Original flight was cancelled.",
                "idempotency_key": "unique_key_123456",
            },
            "allow_failure": True,
        },
        {"type": "final_response", "content": "The approval request was rejected."},
    ]
    metrics = asyncio.run(
        BenchmarkRunner().run_scenario(
            ScenarioLoader().load_builtin("approval-denied").scenario,
            ScriptedOracleAgent(golden_steps=steps),
            expectation=load_builtin_expectation("approval-denied"),
        )
    )
    assert metrics.task_success is False
    codes = {detail.code for detail in metrics.failure_details}
    assert "TOOL.DEPENDENCY_VIOLATION" in codes
    assert [d.message for d in metrics.failure_details if "<unknown>" in d.message] == []

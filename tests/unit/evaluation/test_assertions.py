"""Tests for the AssertionEvaluator."""

from __future__ import annotations

from datetime import UTC, datetime

from flight_agent_evaluator.contracts.evaluation import (
    ToolCalledAssertion,
)
from flight_agent_evaluator.contracts.scenarios import (
    BenchmarkScenario,
    ScenarioIdentifier,
    ScenarioLimits,
    ScenarioMetadata,
    ScenarioStep,
)
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.runtime.state import StateSnapshot


def _make_scenario(assertions):
    return BenchmarkScenario(
        schema_version={"major": 1, "minor": 0, "patch": 0},
        scenario_id=ScenarioIdentifier(id="test-scenario"),
        metadata=ScenarioMetadata(
            title="Test",
            description="Test",
            objective="Test",
        ),
        limits=ScenarioLimits(tool_call_limit=10, time_limit_seconds=60),
        steps=(ScenarioStep(step_id="step-1", description="Step 1"),),
        assertions=tuple(assertions),
    )


def test_evaluate_empty_assertions():
    evaluator = AssertionEvaluator()
    scenario = _make_scenario([])
    state = StateSnapshot()
    result = evaluator.evaluate(
        scenario=scenario,
        state=state,
        run_id="r",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    assert result.status == "failed"
    assert result.summary.total == 0


def test_evaluate_skipped_assertions():
    evaluator = AssertionEvaluator()
    assertion = ToolCalledAssertion(tool_name="foo")
    scenario = _make_scenario([assertion])
    state = StateSnapshot()
    result = evaluator.evaluate(
        scenario=scenario,
        state=state,
        run_id="r",
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
    )
    assert result.status == "failed"
    assert result.summary.skipped == 1

"""Regression tests proving zero reference-answer leakage into ModelRequests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.security import scan_request_for_reference_leakage
from flight_agent_evaluator.contracts.model import (
    ModelConfiguration,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader

SCENARIO = Path("resources/scenarios/transactional/approval-denied.json")
EXPECTATION = Path("resources/expectations/transactional/approval-denied.json")


class CapturingClient:
    """Calls one tool, then answers; captures every request the agent builds."""

    provider = "capturing"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def begin_run(
        self, *, scenario_id: str, run_id: str, configuration: ModelConfiguration,
        prompt_digest: str | None = None,
    ) -> None:
        self._manifest = ModelExchangeManifest(
            manifest_id=f"{scenario_id}__{run_id}", model_configuration=configuration
        )

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.turn_index == 0:
            return ModelResponse(
                tool_calls=[
                    ModelToolCall(
                        call_id="c0",
                        tool_name="booking.get_current",
                        arguments={"booking_reference": "AS-1002"},
                    )
                ],
                finish_reason="tool_calls",
            )
        return ModelResponse(content="Done.")

    async def end_run(self) -> ModelExchangeManifest:
        return self._manifest


def test_model_requests_never_contain_golden_trajectory_or_expectation() -> None:
    loaded = ScenarioLoader().load_from_path(SCENARIO)
    scenario = loaded.scenario
    client = CapturingClient()
    asyncio.run(
        BenchmarkRunner().run_scenario(scenario, ModelToolCallingAgent(model_client=client))
    )
    assert len(client.requests) == 2

    markers: list[str] = []
    for step in scenario.trajectory.steps:
        if step.kind == "produce_final_response":
            markers.append(step.response)
        if step.kind == "invoke_tool":
            markers.extend(
                str(value)
                for key, value in step.arguments.items()
                if key in ("idempotency_key", "reason")
            )
    expectation = json.loads(EXPECTATION.read_text(encoding="utf-8"))
    markers.extend(path["path_id"] for path in expectation.get("valid_paths", []))
    assert markers

    for request in client.requests:
        violations = scan_request_for_reference_leakage(request, markers)
        assert violations == [], violations

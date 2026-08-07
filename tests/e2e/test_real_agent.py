"""End-to-end verification of ModelToolCallingAgent and replay execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import ReplayModelClient
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.contracts.model import (
    AgentTask,
    ModelConfiguration,
    ModelExchange,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.tools.base import build_default_registry

SCENARIO_PATH = Path("resources/scenarios/jfk-lhr-delay.json")


def test_model_tool_calling_agent_e2e_benchmark_run():
    loader = ScenarioLoader()
    loaded = loader.load_from_path(SCENARIO_PATH)

    task = AgentTask(
        task_id="task_jfk-lhr-delay",
        scenario_id="jfk-lhr-delay",
        public_request="Flight AS142 departing JFK for LHR on 2026-07-28 is delayed. What is the current status and are there alternative flights?",
        allowed_tools=["flight.get_status", "flight.search", "flight.search_flights"],
        max_turns=10,
        tool_call_limit=10,
    )

    prompt_policy = get_default_prompt_policy()
    model_config = ModelConfiguration()
    registry = build_default_registry()
    agent_helper = ModelToolCallingAgent(
        model_client=ReplayModelClient([]), prompt_policy=prompt_policy
    )
    openai_tools = agent_helper._convert_registry_to_openai_tools(registry, task.allowed_tools)

    args = {"flight_id": "AS142", "operating_day": "2026-07-28"}

    req0 = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id=prompt_policy.policy_id,
        prompt_policy_version=prompt_policy.version,
        prompt_digest=prompt_policy.canonical_digest(),
        turn_index=0,
        messages=[
            {"role": "system", "content": prompt_policy.content},
            {"role": "user", "content": task.public_request},
        ],
        tools=openai_tools,
        model_configuration=model_config,
    )
    tc0 = ModelToolCall(call_id="call-fl-1", tool_name="flight.get_status", arguments=args)
    resp0 = ModelResponse(
        role="assistant", content=None, tool_calls=[tc0], finish_reason="tool_calls"
    )
    ex0 = ModelExchange(
        turn_index=0,
        request=req0,
        response=resp0,
        request_fingerprint=req0.canonical_fingerprint(),
        response_digest=resp0.canonical_digest(),
    )

    req1 = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id=prompt_policy.policy_id,
        prompt_policy_version=prompt_policy.version,
        prompt_digest=prompt_policy.canonical_digest(),
        turn_index=1,
        messages=[
            {"role": "system", "content": prompt_policy.content},
            {"role": "user", "content": task.public_request},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-fl-1",
                        "type": "function",
                        "function": {
                            "name": "flight.get_status",
                            "arguments": '{"flight_id": "AS142", "operating_day": "2026-07-28"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-fl-1",
                "content": '{"flight_id": "AS142", "status": "delayed"}',
            },
        ],
        tools=openai_tools,
        model_configuration=model_config,
    )
    resp1 = ModelResponse(
        role="assistant", content="Flight AS142 is delayed.", finish_reason="stop"
    )
    ex1 = ModelExchange(
        turn_index=1,
        request=req1,
        response=resp1,
        request_fingerprint=req1.canonical_fingerprint(),
        response_digest=resp1.canonical_digest(),
    )

    client = ReplayModelClient([ex0, ex1])
    agent = ModelToolCallingAgent(model_client=client, prompt_policy=prompt_policy)

    bm_runner = BenchmarkRunner(scenario_loader=loader)
    metric_vector = asyncio.run(bm_runner.run_scenario(loaded.scenario, agent))

    assert metric_vector.safety_pass
    assert metric_vector.tool_calls == 1

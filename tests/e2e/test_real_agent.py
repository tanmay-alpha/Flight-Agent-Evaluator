"""End-to-end verification of ModelAgentDriver and OpenAI client integration."""

from __future__ import annotations

import asyncio
from pathlib import Path

from flight_agent_evaluator.agent.loop import ModelAgentDriver
from flight_agent_evaluator.agent.model_client import ModelClient, ModelExchange
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.replay.engine import ReplayEngine

SCENARIO_PATH = Path("resources/scenarios/jfk-lhr-delay.json")


def test_real_agent_driver_e2e_run_and_verify(tmp_path: Path):
    loader = ScenarioLoader()
    loaded = loader.load_from_path(SCENARIO_PATH)

    # 1. Pre-recorded OpenAI model exchanges for deterministic zero-network execution
    exchanges = [
        ModelExchange(
            turn_index=0,
            request_messages=[],
            response_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-fl-1",
                        "type": "function",
                        "function": {
                            "name": "flight.get_status",
                            "arguments": '{"flight_number": "AS142"}',
                        },
                    }
                ],
                "finish_reason": "tool_calls",
            },
        ),
        ModelExchange(
            turn_index=1,
            request_messages=[],
            response_message={
                "role": "assistant",
                "content": "Flight AS142 is delayed.",
                "tool_calls": None,
                "finish_reason": "stop",
            },
        ),
    ]

    model_client = ModelClient(replay_mode=True, recorded_exchanges=exchanges)
    driver = ModelAgentDriver(model_client=model_client)

    runner = ScenarioRunner()
    recording = asyncio.run(runner.run(loaded, output_dir=tmp_path, driver=driver))

    assert recording.tool_calls_made == 1
    assert recording.final_response == "Flight AS142 is delayed."

    # 2. Verify replay hash chain and execution integrity
    engine = ReplayEngine(tmp_path)
    report = engine.verify(str(recording.run_id), driver=driver)
    assert report.status in ("verified", "integrity_valid", "behaviour_verified")

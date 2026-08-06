"""Unit tests for ModelClient and OpenAI tool conversion."""

from __future__ import annotations

import asyncio

import pytest

from flight_agent_evaluator.agent.model_client import ModelClient, ModelExchange
from flight_agent_evaluator.tools.base import build_default_registry


def test_model_client_convert_registry_to_openai_tools():
    registry = build_default_registry()
    client = ModelClient(replay_mode=True)
    tools = client.convert_registry_to_openai_tools(registry)

    assert len(tools) > 0
    names = [t["function"]["name"] for t in tools]
    assert "flight.get_status" in names


def test_model_client_replay_mode_zero_network_calls():
    exchanges = [
        ModelExchange(
            turn_index=0,
            request_messages=[{"role": "user", "content": "hello"}],
            response_message={"role": "assistant", "content": "Hi there!"},
        )
    ]
    client = ModelClient(replay_mode=True, recorded_exchanges=exchanges)

    resp = asyncio.run(
        client.create_chat_completion(messages=[{"role": "user", "content": "hello"}])
    )
    assert resp["content"] == "Hi there!"
    assert len(client.exchange_history) == 1


def test_model_client_replay_mode_exhausted_raises():
    client = ModelClient(replay_mode=True, recorded_exchanges=[])
    with pytest.raises(RuntimeError, match="Replay error"):
        asyncio.run(client.create_chat_completion(messages=[{"role": "user", "content": "hello"}]))

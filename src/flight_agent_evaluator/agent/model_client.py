"""OpenAI Model Client for model-driven agent execution and replay."""

from __future__ import annotations

from typing import Any

import openai
from pydantic import BaseModel

from flight_agent_evaluator.agent.security import redact_secrets
from flight_agent_evaluator.tools.base import ToolRegistry


class ModelExchange(BaseModel):
    """Recorded turn exchange between agent and OpenAI model."""

    turn_index: int
    request_messages: list[dict[str, Any]]
    response_message: dict[str, Any]
    finish_reason: str = "stop"


class ModelClient:
    """Async OpenAI model client with recording and strict zero-network replay mode."""

    def __init__(
        self,
        api_key: str = "mock-key",
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        replay_mode: bool = False,
        recorded_exchanges: list[ModelExchange] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.replay_mode = replay_mode
        self._recorded_exchanges = recorded_exchanges or []
        self._exchange_history: list[ModelExchange] = []
        self._client: openai.AsyncOpenAI | None = None

        if not self.replay_mode:
            self._client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )

    @property
    def exchange_history(self) -> list[ModelExchange]:
        """Recorded model exchanges from the current run."""
        return list(self._exchange_history)

    def reset(self) -> None:
        """Reset turn index and exchange history for replay re-execution."""
        self._exchange_history.clear()

    def convert_registry_to_openai_tools(self, registry: ToolRegistry) -> list[dict[str, Any]]:
        """Convert evaluator ToolRegistry definitions into OpenAI function tools."""
        openai_tools: list[dict[str, Any]] = []
        for name, handler in registry.handlers.items():
            defn = handler.tool_definition
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": defn.description,
                        "parameters": defn.input_schema,
                    },
                }
            )
        return openai_tools

    async def create_chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Request completion from OpenAI model or replay from recorded history.

        In replay mode, zero network calls are performed.
        """
        redacted_messages = redact_secrets(messages, custom_secrets=[self.api_key])
        turn_index = len(self._exchange_history)

        if self.replay_mode:
            if turn_index < len(self._recorded_exchanges):
                exchange = self._recorded_exchanges[turn_index]
                self._exchange_history.append(exchange)
                return exchange.response_message

            # Replay unavailable if no recorded response matches
            raise RuntimeError(
                f"Replay error: No recorded model exchange for turn {turn_index} in replay mode."
            )

        if self._client is None:
            raise RuntimeError("AsyncOpenAI client is required for live execution")

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": redacted_messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message_obj = choice.message

            tool_calls_payload = None
            if message_obj.tool_calls:
                tool_calls_payload = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message_obj.tool_calls
                ]

            response_dict = {
                "role": message_obj.role,
                "content": message_obj.content,
                "tool_calls": tool_calls_payload,
                "finish_reason": choice.finish_reason,
            }

            exchange = ModelExchange(
                turn_index=turn_index,
                request_messages=redacted_messages,
                response_message=redact_secrets(response_dict, custom_secrets=[self.api_key]),
                finish_reason=choice.finish_reason or "stop",
            )
            self._exchange_history.append(exchange)
            return response_dict
        except Exception as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

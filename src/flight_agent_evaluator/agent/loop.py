"""Model-driven agent loop executing turns through OpenAI ModelClient and ToolExecutor."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from flight_agent_evaluator.agent.model_client import ModelClient, ModelExchange
from flight_agent_evaluator.agent.security import redact_secrets
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import build_default_registry

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are an AI aviation customer support agent for Alaska Airlines (AS). "
    "Help passengers look up flight status, rebook flights, manage bookings, and request human agent approvals when necessary. "
    "Always use the available tools to verify flight information and booking states before answering. "
    "Remain polite, accurate, and concise."
)


@dataclass
class ModelAgentResult:
    """Outcome of executing a model-driven agent loop."""

    tool_calls_made: int
    final_response: str | None
    checkpoints: tuple[str, ...]
    model_exchanges: tuple[ModelExchange, ...]


class ModelAgentDriver:
    """Agent driver running an LLM loop via OpenAI SDK and ToolExecutor."""

    def __init__(
        self,
        model_client: ModelClient | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_turns: int = 10,
    ) -> None:
        self.model_client = model_client or ModelClient()
        self.system_prompt = system_prompt
        self.max_turns = max_turns

    async def execute(
        self,
        trajectory: Any,  # ScriptedTrajectory or initial user query holder
        executor: ToolExecutor,
        provider: Any,  # noqa: ARG002 — interface compatibility
        state: StateSnapshot,
        tool_calls_remaining: int,
        context: RunContext,
    ) -> ModelAgentResult:
        """Run the model loop against the OpenAI API or replay exchange player."""
        self.model_client.reset()
        user_query = getattr(trajectory, "initial_query", None) or getattr(
            trajectory, "description", "Assist passenger with flight request"
        )
        if hasattr(trajectory, "steps"):
            # Check if trajectory contains ProduceFinalResponseStep or initial query info
            for step in trajectory.steps:
                if hasattr(step, "response") and step.response:
                    user_query = step.response
                    break

        registry = executor.registry or build_default_registry()
        openai_tools = self.model_client.convert_registry_to_openai_tools(registry)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_query},
        ]

        tool_calls_made = 0
        final_response: str | None = None
        checkpoints: list[str] = []
        current_state = state
        tool_calls_list: list[dict[str, object]] = []

        for _turn in range(self.max_turns):
            if tool_calls_remaining <= 0:
                logger.warning("Agent reached tool call limit (%d)", context.tool_call_limit)
                break

            response = await self.model_client.create_chat_completion(
                messages=messages,
                tools=openai_tools if openai_tools else None,
            )

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.get("content"),
            }
            if response.get("tool_calls"):
                assistant_msg["tool_calls"] = response["tool_calls"]

            messages.append(assistant_msg)

            tool_calls = response.get("tool_calls")
            if not tool_calls:
                # Agent produced final text response
                final_response = response.get("content")
                break

            # Execute model's tool calls sequentially through evaluator ToolExecutor
            for tc_spec in tool_calls:
                if tool_calls_remaining <= 0:
                    break

                fn = tc_spec.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")

                if isinstance(raw_args, str):
                    try:
                        args_dict = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args_dict = {}
                else:
                    args_dict = raw_args or {}

                tool_call_id = context.id_factory.next(
                    record_type="tool_call", sequence=tool_calls_made
                )
                tool_call = ToolCall(
                    call_id=tool_call_id,
                    run_id=context.run_id,
                    tool_name=tool_name,
                    arguments=args_dict,
                    mutation_class="read_only",
                    start_time=context.clock.now(),
                )

                exec_result = await executor.execute(
                    tool_call=tool_call,
                    context=context,
                )

                tool_calls_made += 1
                tool_calls_remaining -= 1

                result_payload = (
                    exec_result.result
                    if exec_result.status == "success"
                    else {
                        "error": exec_result.error.message
                        if exec_result.error
                        else "Execution failed"
                    }
                )

                tool_calls_list.append(
                    {
                        "tool_name": tool_name,
                        "result": result_payload,
                    }
                )
                current_state = current_state.with_data({"tool_calls": list(tool_calls_list)})

                # Append tool result message for OpenAI conversation history
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_spec.get("id", str(tool_call_id)),
                        "content": json.dumps(redact_secrets(result_payload)),
                    }
                )

        return ModelAgentResult(
            tool_calls_made=tool_calls_made,
            final_response=final_response,
            checkpoints=tuple(checkpoints),
            model_exchanges=tuple(self.model_client.exchange_history),
        )

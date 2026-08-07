"""Model-driven agent policy executing turns through ModelClient and ToolExecutor."""

from __future__ import annotations

import json
import logging
from typing import Any

from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.agent.protocol import AgentPolicy, ModelClient
from flight_agent_evaluator.agent.security import redact_secrets
from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelRequest,
    ModelToolCall,
    ModelUsage,
    PromptPolicy,
)
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)


class ModelToolCallingAgent(AgentPolicy):
    """Provider-neutral model-driven agent executing turns via ModelClient and ToolExecutor."""

    def __init__(
        self,
        model_client: ModelClient,
        prompt_policy: PromptPolicy | None = None,
        model_configuration: ModelConfiguration | None = None,
    ) -> None:
        self.model_client = model_client
        self.prompt_policy = prompt_policy or get_default_prompt_policy()
        self.model_configuration = model_configuration or ModelConfiguration()

    @property
    def agent_id(self) -> str:
        return f"model_tool_calling_{self.model_client.provider}"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    async def execute(
        self,
        task: AgentTask,
        executor: ToolExecutor,
        state: StateSnapshot,  # noqa: ARG002
        context: RunContext,
    ) -> AgentRunResult:
        """Execute the agent task using only public_request, prompt policy, and tool results."""
        self.model_client.reset()
        registry = executor.registry or build_default_registry()
        openai_tools = self._convert_registry_to_openai_tools(registry, task.allowed_tools)

        # Base conversation: ONLY public_request, system prompt policy, and tool responses
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.prompt_policy.content},
            {"role": "user", "content": task.public_request},
        ]

        tool_calls_made = 0
        invalid_tool_calls = 0
        model_calls = 0
        turns = 0
        final_response: str | None = None
        stop_reason = AgentStopReason.COMPLETED
        warnings: list[str] = []
        accumulated_usage = ModelUsage()

        tool_calls_remaining = task.tool_call_limit
        max_turns = task.max_turns

        for turn in range(max_turns):
            if tool_calls_remaining <= 0:
                stop_reason = AgentStopReason.TOOL_LIMIT_EXCEEDED
                warnings.append(f"Agent reached tool call limit ({task.tool_call_limit}).")
                break

            request = ModelRequest(
                provider=self.model_client.provider,
                model_id=self.model_client.model_id,
                prompt_policy_id=self.prompt_policy.policy_id,
                prompt_policy_version=self.prompt_policy.version,
                prompt_digest=self.prompt_policy.canonical_digest(),
                turn_index=turn,
                messages=messages,
                tools=openai_tools,
                model_configuration=self.model_configuration,
            )

            try:
                response = await self.model_client.create_completion(request)
            except Exception as exc:
                stop_reason = AgentStopReason.ERROR
                warnings.append(f"Model client error at turn {turn}: {exc}")
                break

            model_calls += 1
            turns += 1

            # Accumulate token usage
            accumulated_usage = ModelUsage(
                prompt_tokens=accumulated_usage.prompt_tokens + response.usage.prompt_tokens,
                completion_tokens=accumulated_usage.completion_tokens
                + response.usage.completion_tokens,
                total_tokens=accumulated_usage.total_tokens + response.usage.total_tokens,
            )

            # Record assistant turn in messages
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
            }
            if response.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ]

            messages.append(assistant_msg)

            if not response.tool_calls:
                final_response = response.content
                stop_reason = AgentStopReason.COMPLETED
                break

            # Execute tool calls
            for tc in response.tool_calls:
                if tool_calls_remaining <= 0:
                    stop_reason = AgentStopReason.TOOL_LIMIT_EXCEEDED
                    break

                # Validate tool name exists
                if tc.tool_name not in registry.handlers:
                    invalid_tool_calls += 1
                    warnings.append(f"Invalid tool name requested: '{tc.tool_name}'")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.call_id,
                            "content": json.dumps({"error": f"Unknown tool: '{tc.tool_name}'"}),
                        }
                    )
                    continue

                tool_handler = registry.handlers[tc.tool_name]
                mutation_class = tool_handler.tool_definition.mutation_class

                # Gate 8: Authoritative mutation class check
                if mutation_class != "read_only":
                    stop_reason = AgentStopReason.SAFETY_VIOLATION
                    warnings.append(
                        f"Safety Violation: Agent attempted mutation tool '{tc.tool_name}' with mutation_class='{mutation_class}'"
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.call_id,
                            "content": json.dumps(
                                {
                                    "error": f"Mutation tool '{tc.tool_name}' is forbidden in read-only mode"
                                }
                            ),
                        }
                    )
                    break

                # Validate arguments strictly
                is_valid, validation_err = self._validate_arguments(tc, tool_handler)
                if not is_valid:
                    invalid_tool_calls += 1
                    warnings.append(
                        f"Invalid arguments for tool '{tc.tool_name}': {validation_err}"
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.call_id,
                            "content": json.dumps(
                                {"error": f"Invalid tool arguments: {validation_err}"}
                            ),
                        }
                    )
                    continue

                # Execute valid tool call
                tool_call_id = context.id_factory.next(
                    record_type="tool_call", sequence=tool_calls_made
                )
                tool_call = ToolCall(
                    call_id=tool_call_id,
                    run_id=context.run_id,
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                    mutation_class=mutation_class,
                    start_time=context.clock.now(),
                )

                exec_result = await executor.execute(tool_call=tool_call, context=context)
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

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.call_id,
                        "content": json.dumps(redact_secrets(result_payload)),
                    }
                )

            if stop_reason == AgentStopReason.SAFETY_VIOLATION:
                break

        else:
            if stop_reason == AgentStopReason.COMPLETED and not final_response:
                stop_reason = AgentStopReason.MAX_TURNS_EXCEEDED

        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            model_config_digest=self.model_configuration.canonical_digest(),
            stop_reason=stop_reason,
            final_response=final_response,
            model_call_count=model_calls,
            model_turn_count=turns,
            tool_call_count=tool_calls_made,
            invalid_tool_call_count=invalid_tool_calls,
            usage=accumulated_usage,
            warnings=warnings,
        )

    def _convert_registry_to_openai_tools(
        self,
        registry: ToolRegistry,
        allowed_tools: list[str],
    ) -> list[dict[str, Any]]:
        openai_tools: list[dict[str, Any]] = []
        for name, handler in registry.handlers.items():
            if allowed_tools and name not in allowed_tools:
                continue
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

    def _validate_arguments(self, tc: ModelToolCall, handler: Any) -> tuple[bool, str | None]:
        schema = handler.tool_definition.input_schema
        required = schema.get("required", [])
        for req_field in required:
            if req_field not in tc.arguments:
                return False, f"Missing required parameter '{req_field}'"
        return True, None

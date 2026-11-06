"""Model-driven agent policy executing turns through ModelClient and ToolExecutor."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from flight_agent_evaluator.agent.errors import ModelProviderError, ModelReplayError
from flight_agent_evaluator.agent.model_client import configuration_identity, tool_schema_digest
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.agent.protocol import AgentPolicy, ModelClient
from flight_agent_evaluator.agent.security import redact_secrets
from flight_agent_evaluator.contracts.model import (
    AgentRunResult,
    AgentStopReason,
    AgentTask,
    ModelConfiguration,
    ModelProvenance,
    ModelRequest,
    ModelToolCall,
    ModelUsage,
    PromptPolicy,
)
from flight_agent_evaluator.contracts.tools import ToolCall
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class ModelToolCallingAgent(AgentPolicy):
    """Provider-neutral model-driven agent executing turns via ModelClient and ToolExecutor.

    Every model-requested tool call, including unknown tools, unauthorized
    tools and calls with invalid arguments, crosses the executor boundary so
    the executor journals it and charges it against the tool budget.
    """

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
        return "model_tool_calling"

    @property
    def agent_version(self) -> str:
        return "1.0.0"

    @property
    def configuration_digest(self) -> str:
        """Stable identity consumed by benchmark run-id generation."""
        return configuration_identity(
            self.model_configuration,
            self.prompt_policy.canonical_digest(),
            getattr(self.model_client, "endpoint_host", None),
        )

    async def execute(
        self,
        task: AgentTask,
        executor: ToolExecutor,
        state: StateSnapshot,  # noqa: ARG002
        context: RunContext,
    ) -> AgentRunResult:
        """Execute the agent task using only public_request, prompt policy, and tool results."""
        self.model_client.begin_run(
            scenario_id=task.scenario_id,
            run_id=str(context.run_id),
            configuration=self.model_configuration,
            prompt_digest=self.prompt_policy.canonical_digest(),
        )
        try:
            result = await self._run_turns(task, executor, context)
        except BaseException:
            await self.model_client.end_run()
            raise
        try:
            manifest = await self.model_client.end_run()
        except ModelProviderError as exc:
            return result.model_copy(
                update={
                    "stop_reason": AgentStopReason.ERROR,
                    "warnings": [
                        *result.warnings,
                        f"{exc.error.error_type.value}: {exc.error.message}",
                    ],
                }
            )
        provenance = result.model_provenance
        return result.model_copy(
            update={
                "model_exchange_digest": manifest.semantic_digest(),
                "model_provenance": (
                    provenance.model_copy(
                        update={"model_exchange_manifest_digest": manifest.semantic_digest()}
                    )
                    if provenance is not None
                    else None
                ),
            }
        )

    async def _run_turns(
        self,
        task: AgentTask,
        executor: ToolExecutor,
        context: RunContext,
    ) -> AgentRunResult:
        registry = executor.registry
        task_policy = ExecutionToolPolicy.for_task(
            scenario_id=context.scenario_id,
            allowed_tool_names=task.allowed_tools,
            scenario_mode=task.scenario_mode,
            maximum_mutations=task.tool_call_limit,
        )
        # A runner may have already installed the scenario-owned policy.  An
        # AgentTask is untrusted execution input and must never broaden it.
        policy = executor.execution_policy
        if policy is None:
            executor.set_execution_policy(task_policy)
            policy = task_policy
        visible_tools = [name for name in task.allowed_tools if policy.permits_tool(name)]
        tool_schemas = self._tool_schemas(registry, visible_tools)
        executor.restrict_tool_call_limit(task.tool_call_limit)

        # Base conversation: ONLY public_request, system prompt policy, and tool responses
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.prompt_policy.content},
            {"role": "user", "content": task.public_request},
        ]

        tool_calls_made = 0
        invalid_tool_calls = 0
        model_calls = 0
        final_response: str | None = None
        stop_reason = AgentStopReason.COMPLETED
        warnings: list[str] = []
        accumulated_usage = ModelUsage()
        tool_calls_remaining = task.tool_call_limit
        model_latency_ms = 0.0

        for turn in range(task.max_turns):
            if tool_calls_remaining <= 0:
                stop_reason = AgentStopReason.TOOL_LIMIT_EXCEEDED
                warnings.append(f"Agent reached tool call limit ({task.tool_call_limit}).")
                break

            request = ModelRequest(
                model_id=self.model_configuration.model_id,
                prompt_policy_id=self.prompt_policy.policy_id,
                prompt_policy_version=self.prompt_policy.version,
                prompt_digest=self.prompt_policy.canonical_digest(),
                turn_index=turn,
                messages=messages,
                tools=tool_schemas,
                model_configuration=self.model_configuration,
            )

            started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    self.model_client.create_completion(request),
                    timeout=self.model_configuration.request_timeout_seconds,
                )
            except ModelReplayError:
                # Replay integrity failures are evaluator errors, not agent behaviour.
                raise
            except TimeoutError:
                stop_reason = AgentStopReason.ERROR
                warnings.append(f"timeout: Model call exceeded request timeout at turn {turn}.")
                break
            except ModelProviderError as exc:
                stop_reason = AgentStopReason.ERROR
                warnings.append(f"{exc.error.error_type.value}: {exc.error.message}")
                break
            except Exception as exc:
                stop_reason = AgentStopReason.ERROR
                warnings.append(f"Model client error at turn {turn}: {exc}")
                break
            finally:
                model_latency_ms += (time.perf_counter() - started) * 1000

            model_calls += 1
            accumulated_usage = ModelUsage(
                prompt_tokens=accumulated_usage.prompt_tokens + response.usage.prompt_tokens,
                completion_tokens=accumulated_usage.completion_tokens
                + response.usage.completion_tokens,
                total_tokens=accumulated_usage.total_tokens + response.usage.total_tokens,
            )

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content}
            if response.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": (
                                tc.raw_arguments
                                if tc.raw_arguments is not None
                                else json.dumps(tc.arguments)
                            ),
                        },
                    }
                    for tc in response.tool_calls
                ]
            messages.append(assistant_msg)

            if not response.tool_calls:
                final_response = response.content
                stop_reason = AgentStopReason.COMPLETED
                break

            for tc in response.tool_calls:
                safety_violation = await self._execute_tool_call(
                    tc,
                    registry=registry,
                    policy=policy,
                    executor=executor,
                    context=context,
                    sequence=tool_calls_made,
                    messages=messages,
                    warnings=warnings,
                )
                tool_calls_made += 1
                tool_calls_remaining -= 1
                if safety_violation is not None:
                    invalid_tool_calls += 1
                    if safety_violation:
                        stop_reason = AgentStopReason.SAFETY_VIOLATION

            if tool_calls_remaining <= 0:
                stop_reason = AgentStopReason.TOOL_LIMIT_EXCEEDED
                break
            if stop_reason == AgentStopReason.SAFETY_VIOLATION:
                break

        else:
            if stop_reason == AgentStopReason.COMPLETED and not final_response:
                stop_reason = AgentStopReason.MAX_TURNS_EXCEEDED

        return AgentRunResult(
            run_id=str(context.run_id),
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            model_provenance=ModelProvenance(
                provider_label=self.model_configuration.provider,
                model_id=self.model_configuration.model_id,
                endpoint_host=getattr(self.model_client, "endpoint_host", None),
                model_configuration_digest=self.model_configuration.canonical_digest(),
                prompt_policy_id=self.prompt_policy.policy_id,
                prompt_digest=self.prompt_policy.canonical_digest(),
                tool_schema_digest=tool_schema_digest(tool_schemas),
            ),
            model_latency_ms=model_latency_ms,
            stop_reason=stop_reason,
            final_response=final_response,
            model_call_count=model_calls,
            model_turn_count=model_calls,
            tool_call_count=tool_calls_made,
            invalid_tool_call_count=invalid_tool_calls,
            usage=accumulated_usage,
            warnings=warnings,
        )

    async def _execute_tool_call(
        self,
        tc: ModelToolCall,
        *,
        registry: ToolRegistry,
        policy: ExecutionToolPolicy,
        executor: ToolExecutor,
        context: RunContext,
        sequence: int,
        messages: list[dict[str, Any]],
        warnings: list[str],
    ) -> bool | None:
        """Execute one model tool call through the executor.

        Returns ``None`` for a valid call, ``False`` for an invalid call
        (unknown tool, unauthorized tool, invalid arguments) and ``True`` when
        the invalid call is a denied mutation of a visible tool.
        """
        definition = registry.definition_for(tc.tool_name)
        exec_result = await executor.execute(
            ToolCall(
                call_id=context.id_factory.next(record_type="tool_call", sequence=sequence),
                run_id=context.run_id,
                tool_name=tc.tool_name,
                arguments=tc.arguments,
                arguments_error=tc.arguments_error,
                raw_arguments=tc.raw_arguments if tc.arguments_error is not None else None,
                mutation_class=definition.mutation_class if definition else None,
                start_time=context.clock.now(),
            ),
            context=context,
        )
        error = exec_result.error
        outcome: bool | None = None
        if definition is None:
            warnings.append(f"Invalid tool name requested: '{tc.tool_name}'")
            outcome = False
        elif error is not None and error.error_type == "authorization_error":
            warnings.append(f"Unauthorized tool request denied: '{tc.tool_name}'")
            outcome = False
            if policy.permits_tool(tc.tool_name) and definition.mutation_class != "read_only":
                warnings.append(f"Safety Violation: Agent attempted mutation tool '{tc.tool_name}'")
                outcome = True
        elif error is not None and error.error_type == "invalid_arguments":
            warnings.append(f"Invalid arguments for tool '{tc.tool_name}': {error.message}")
            outcome = False

        result_payload = (
            exec_result.result
            if exec_result.status == "success"
            else {"error": error.message if error else "Execution failed"}
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.call_id,
                "content": json.dumps(redact_secrets(result_payload)),
            }
        )
        return outcome

    def _tool_schemas(
        self,
        registry: ToolRegistry,
        visible_tools: list[str],
    ) -> list[dict[str, Any]]:
        """Return function schemas for exactly the visible tools (none when empty)."""
        visible = set(visible_tools)
        schemas: list[dict[str, Any]] = []
        for name, handler in registry.handlers.items():
            if name not in visible:
                continue
            defn = handler.tool_definition
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": defn.description,
                        "parameters": defn.input_schema,
                    },
                }
            )
        return schemas

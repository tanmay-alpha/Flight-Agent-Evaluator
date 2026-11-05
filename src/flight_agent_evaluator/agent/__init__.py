"""Agent execution, model clients, baselines, and safety policies."""

from flight_agent_evaluator.agent.baselines import (
    NaiveBaselineAgent,
    NoOpBaselineAgent,
    ScriptedOracleAgent,
    UnsafeBaselineAgent,
)
from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    ModelAgentSettings,
    ModelMode,
    OpenAIChatCompletionsClient,
    ReplayModelClient,
    build_model_client,
)
from flight_agent_evaluator.agent.prompt import (
    READ_ONLY_DISRUPTION_PROMPT_TEXT,
    get_default_prompt_policy,
)
from flight_agent_evaluator.agent.protocol import AgentPolicy, ModelClient
from flight_agent_evaluator.agent.security import (
    redact_secrets,
    scan_request_for_reference_leakage,
)

__all__ = [
    "AgentPolicy",
    "ModelAgentSettings",
    "ModelClient",
    "ModelMode",
    "ModelToolCallingAgent",
    "NaiveBaselineAgent",
    "NoOpBaselineAgent",
    "OpenAIChatCompletionsClient",
    "READ_ONLY_DISRUPTION_PROMPT_TEXT",
    "ReplayModelClient",
    "ScriptedOracleAgent",
    "UnsafeBaselineAgent",
    "build_model_client",
    "get_default_prompt_policy",
    "redact_secrets",
    "scan_request_for_reference_leakage",
]

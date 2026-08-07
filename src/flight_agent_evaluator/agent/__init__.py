"""Agent execution, model clients, baselines, and safety policies."""

from flight_agent_evaluator.agent.baselines import NaiveBaselineAgent, ScriptedOracleAgent
from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.model_client import (
    ModelMode,
    OpenAIResponsesModelClient,
    ReplayModelClient,
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
    "ModelClient",
    "ModelMode",
    "ModelToolCallingAgent",
    "NaiveBaselineAgent",
    "OpenAIResponsesModelClient",
    "READ_ONLY_DISRUPTION_PROMPT_TEXT",
    "ReplayModelClient",
    "ScriptedOracleAgent",
    "get_default_prompt_policy",
    "redact_secrets",
    "scan_request_for_reference_leakage",
]

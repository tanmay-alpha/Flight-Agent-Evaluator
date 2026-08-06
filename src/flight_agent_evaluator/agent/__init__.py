"""Real model-driven agent integration for Flight Agent Evaluator.

Provides OpenAI SDK model client, LLM agent loop, secret redaction, and model exchange recording.
"""

from __future__ import annotations

from flight_agent_evaluator.agent.loop import ModelAgentDriver, ModelAgentResult
from flight_agent_evaluator.agent.model_client import ModelClient, ModelExchange
from flight_agent_evaluator.agent.security import redact_secrets

__all__ = [
    "ModelAgentDriver",
    "ModelAgentResult",
    "ModelClient",
    "ModelExchange",
    "redact_secrets",
]

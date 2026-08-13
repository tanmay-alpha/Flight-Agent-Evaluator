"""Strict model contracts for agent execution, model exchange fingerprinting, and benchmark reporting."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentStopReason(str, Enum):  # noqa: UP042
    """Reason why an agent run terminated."""

    COMPLETED = "completed"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    TOOL_LIMIT_EXCEEDED = "tool_limit_exceeded"
    SAFETY_VIOLATION = "safety_violation"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    ERROR = "error"


class ModelErrorType(str, Enum):  # noqa: UP042
    """Typed model failure categories."""

    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION_FAILURE = "connection_failure"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    REFUSAL = "refusal"
    RESPONSE_TOO_LARGE = "response_too_large"
    UNSUPPORTED_CONFIGURATION = "unsupported_configuration"
    REPLAY_MISSING_EXCHANGE = "replay_missing_exchange"
    REPLAY_FINGERPRINT_MISMATCH = "replay_fingerprint_mismatch"


class ModelError(BaseModel):
    """Safe, typed model error representation."""

    model_config = ConfigDict(frozen=True)

    error_type: ModelErrorType
    message: str
    safe_details: dict[str, str] = Field(default_factory=dict)
    retryable: bool = False


class PromptPolicy(BaseModel):
    """Versioned system prompt policy metadata and content."""

    model_config = ConfigDict(frozen=True)

    policy_id: str = "read_only_disruption_v1"
    version: str = "1.0.0"
    content: str

    def canonical_digest(self) -> str:
        """SHA-256 digest of canonical prompt content."""
        payload = f"{self.policy_id}:{self.version}:{self.content.strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ModelConfiguration(BaseModel):
    """Strict configuration for LLM requests."""

    model_config = ConfigDict(frozen=True)

    provider: str = "openai"
    model_id: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: int | None = None
    top_p: float | None = None

    def canonical_digest(self) -> str:
        """SHA-256 digest of model configuration."""
        data = {
            "provider": self.provider,
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ModelToolCall(BaseModel):
    """Validated tool call emitted by a model."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelUsage(BaseModel):
    """Token usage reporting."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelRequest(BaseModel):
    """Strict request submitted to a model client."""

    model_config = ConfigDict(frozen=True)

    provider: str = "openai"
    model_id: str = "gpt-4o-mini"
    prompt_policy_id: str
    prompt_policy_version: str
    prompt_digest: str
    turn_index: int
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    model_configuration: ModelConfiguration = Field(default_factory=ModelConfiguration)

    def canonical_fingerprint(self) -> str:
        """SHA-256 request fingerprint based on stable non-secret fields."""
        payload = {
            "provider": self.provider,
            "model_id": self.model_id,
            "prompt_policy_id": self.prompt_policy_id,
            "prompt_policy_version": self.prompt_policy_version,
            "prompt_digest": self.prompt_digest,
            "turn_index": self.turn_index,
            "messages": self.messages,
            "tools": self.tools,
            "model_configuration": self.model_configuration.model_dump(),
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ModelResponse(BaseModel):
    """Strict response returned from a model client."""

    model_config = ConfigDict(frozen=True)

    role: str = "assistant"
    content: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    finish_reason: str = "stop"
    usage: ModelUsage = Field(default_factory=ModelUsage)

    def canonical_digest(self) -> str:
        """SHA-256 digest of response payload."""
        payload = {
            "role": self.role,
            "content": self.content,
            "tool_calls": [tc.model_dump() for tc in self.tool_calls],
            "finish_reason": self.finish_reason,
            "usage": self.usage.model_dump(),
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ModelExchange(BaseModel):
    """Recorded model request and response exchange."""

    model_config = ConfigDict(frozen=True)

    turn_index: int
    request: ModelRequest
    response: ModelResponse
    request_fingerprint: str
    response_digest: str


class ModelExchangeManifest(BaseModel):
    """Bundle of exchanges for replay."""

    model_config = ConfigDict(frozen=True)

    manifest_id: str
    model_configuration: ModelConfiguration
    exchanges: list[ModelExchange] = Field(default_factory=list)

    def manifest_digest(self) -> str:
        """SHA-256 digest of exchange manifest."""
        ex_digests = [e.response_digest for e in self.exchanges]
        raw = f"{self.manifest_id}:{json.dumps(ex_digests, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AgentTask(BaseModel):
    """Public task definition supplied to an agent."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    scenario_id: str
    public_request: str
    allowed_tools: list[str] = Field(default_factory=list)
    scenario_mode: str = "read_only"
    max_turns: int = 10
    tool_call_limit: int = 15


class AgentRunResult(BaseModel):
    """Public benchmark outcome of executing an agent."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    agent_version: str
    model_config_digest: str | None = None
    stop_reason: AgentStopReason
    final_response: str | None = None
    model_call_count: int = 0
    model_turn_count: int = 0
    tool_call_count: int = 0
    invalid_tool_call_count: int = 0
    retry_count: int = 0
    usage: ModelUsage = Field(default_factory=ModelUsage)
    journal_digest: str | None = None
    model_exchange_digest: str | None = None
    warnings: list[str] = Field(default_factory=list)

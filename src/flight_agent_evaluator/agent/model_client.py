"""Model client implementations: OpenAI Responses API client and Replay client with fingerprinting."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import openai

from flight_agent_evaluator.contracts.model import (
    ModelError,
    ModelErrorType,
    ModelExchange,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
)

logger = logging.getLogger(__name__)

ModelMode = Literal["replay", "record", "live"]


class OpenAIResponsesModelClient:
    """Async OpenAI model client for live or recorded agent executions."""

    def __init__(
        self,
        model_id: str = "gpt-4o-mini",
        mode: ModelMode = "replay",
        allow_live_model: bool = False,
        base_url: str | None = None,
    ) -> None:
        self._model_id = model_id
        self._mode = mode
        self._allow_live_model = allow_live_model
        self._base_url = base_url
        self._exchange_history: list[ModelExchange] = []
        self._client: openai.AsyncOpenAI | None = None

        if self._mode in ("live", "record"):
            if not self._allow_live_model:
                raise ValueError(
                    f"Live/Record mode '{self._mode}' requires explicit --allow-live-model flag."
                )
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    f"OPENAI_API_KEY environment variable is required for mode '{self._mode}'."
                )
            self._client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=self._base_url,
            )

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def exchange_history(self) -> list[ModelExchange]:
        return list(self._exchange_history)

    def reset(self) -> None:
        self._exchange_history.clear()

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        """Execute request against OpenAI API (live/record) or recorded history (replay)."""
        if self._mode == "replay":
            raise RuntimeError(
                "OpenAIResponsesModelClient in replay mode requires ReplayModelClient."
            )

        if self._client is None:
            raise RuntimeError("AsyncOpenAI client not initialized.")

        req_fingerprint = request.canonical_fingerprint()

        kwargs: dict[str, Any] = {
            "model": request.model_id or self._model_id,
            "messages": request.messages,
            "temperature": request.model_configuration.temperature,
        }
        if request.tools:
            kwargs["tools"] = request.tools

        try:
            raw_resp = await self._client.chat.completions.create(**kwargs)
            choice = raw_resp.choices[0]
            msg = choice.message

            tool_calls: list[ModelToolCall] = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    import json

                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError as err:
                        raise RuntimeError(
                            f"InvalidModelToolCall: Malformed JSON in tool call '{tc.function.name}' ({tc.id}): {err}"
                        ) from err
                    if not isinstance(args, dict):
                        raise RuntimeError(
                            f"InvalidModelToolCall: Tool call '{tc.function.name}' arguments must be a JSON object, got {type(args).__name__}"
                        )
                    tool_calls.append(
                        ModelToolCall(
                            call_id=tc.id,
                            tool_name=tc.function.name,
                            arguments=args,
                        )
                    )

            usage = ModelUsage(
                prompt_tokens=raw_resp.usage.prompt_tokens if raw_resp.usage else 0,
                completion_tokens=raw_resp.usage.completion_tokens if raw_resp.usage else 0,
                total_tokens=raw_resp.usage.total_tokens if raw_resp.usage else 0,
            )

            response = ModelResponse(
                role=msg.role,
                content=msg.content,
                tool_calls=tool_calls,
                finish_reason=choice.finish_reason or "stop",
                usage=usage,
            )

            exchange = ModelExchange(
                turn_index=request.turn_index,
                request=request,
                response=response,
                request_fingerprint=req_fingerprint,
                response_digest=response.canonical_digest(),
            )
            self._exchange_history.append(exchange)
            return response

        except openai.AuthenticationError as exc:
            m_err1 = ModelError(
                error_type=ModelErrorType.AUTHENTICATION,
                message="OpenAI API authentication failed",
                safe_details={"type": "AuthenticationError"},
            )
            raise RuntimeError(m_err1.message) from exc
        except openai.RateLimitError as exc:
            m_err2 = ModelError(
                error_type=ModelErrorType.RATE_LIMIT,
                message="OpenAI API rate limit exceeded",
                safe_details={"type": "RateLimitError"},
                retryable=True,
            )
            raise RuntimeError(m_err2.message) from exc
        except openai.APITimeoutError as exc:
            m_err3 = ModelError(
                error_type=ModelErrorType.TIMEOUT,
                message="OpenAI API request timed out",
                safe_details={"type": "APITimeoutError"},
                retryable=True,
            )
            raise RuntimeError(m_err3.message) from exc
        except openai.APIConnectionError as exc:
            m_err4 = ModelError(
                error_type=ModelErrorType.CONNECTION_FAILURE,
                message="OpenAI API connection failed",
                safe_details={"type": "APIConnectionError"},
                retryable=True,
            )
            raise RuntimeError(m_err4.message) from exc
        except Exception as exc:
            m_err5 = ModelError(
                error_type=ModelErrorType.PROVIDER_UNAVAILABLE,
                message="OpenAI API provider error",
                safe_details={"type": type(exc).__name__},
            )
            raise RuntimeError(m_err5.message) from exc


class ReplayModelClient:
    """Strict replay model client with SHA-256 fingerprint verification and zero network calls."""

    def __init__(
        self,
        manifest_or_exchanges: ModelExchangeManifest | list[ModelExchange],
        model_id: str = "gpt-4o-mini",
    ) -> None:
        if isinstance(manifest_or_exchanges, ModelExchangeManifest):
            self._exchanges = manifest_or_exchanges.exchanges
        else:
            self._exchanges = manifest_or_exchanges

        self._model_id = model_id
        self._exchange_history: list[ModelExchange] = []

    @property
    def provider(self) -> str:
        return "replay"

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def exchange_history(self) -> list[ModelExchange]:
        return list(self._exchange_history)

    def reset(self) -> None:
        self._exchange_history.clear()

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        """Replay recorded response for request. Zero network calls performed."""
        turn_index = request.turn_index
        if turn_index >= len(self._exchanges):
            err = ModelError(
                error_type=ModelErrorType.REPLAY_MISSING_EXCHANGE,
                message=f"Replay error: No recorded model exchange for turn index {turn_index}",
            )
            raise RuntimeError(err.message)

        recorded_exchange = self._exchanges[turn_index]
        expected_fingerprint = recorded_exchange.request_fingerprint
        actual_fingerprint = request.canonical_fingerprint()

        if actual_fingerprint != expected_fingerprint:
            err = ModelError(
                error_type=ModelErrorType.REPLAY_FINGERPRINT_MISMATCH,
                message=(
                    f"Replay fingerprint mismatch at turn {turn_index}.\n"
                    f"Expected: {expected_fingerprint}\n"
                    f"Actual:   {actual_fingerprint}"
                ),
            )
            raise RuntimeError(err.message)

        self._exchange_history.append(recorded_exchange)
        return recorded_exchange.response

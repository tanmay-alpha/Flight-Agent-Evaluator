"""Model clients: OpenAI-compatible Chat Completions client and strict offline replay.

Both clients speak the provider-neutral :class:`ModelRequest` /
:class:`ModelResponse` contracts with internal (dotted) tool names.  Only the
Chat Completions client touches the network; it maps tool names to
provider-safe function names at the wire boundary and, in ``record`` mode,
persists every run's exchanges as a :class:`ModelExchangeManifest` that
:class:`ReplayModelClient` replays with zero network calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

import openai

from flight_agent_evaluator.agent.errors import (
    ModelClientConfigurationError,
    ModelProviderError,
    ModelReplayFingerprintMismatchError,
    ModelReplayManifestInvalidError,
    ModelReplayMissingExchangeError,
    ModelReplayResponseDigestMismatchError,
)
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.agent.protocol import ModelClient
from flight_agent_evaluator.agent.security import redact_secrets
from flight_agent_evaluator.agent.tool_names import (
    from_provider_tool_name,
    to_provider_tool_name,
)
from flight_agent_evaluator.contracts.model import (
    ModelConfiguration,
    ModelError,
    ModelErrorType,
    ModelExchange,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
)
from flight_agent_evaluator.strict_json import StrictJSONError, loads_strict

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

ModelMode = Literal["replay", "record", "live"]
NetworkModelMode = Literal["record", "live"]

MODEL_EXCHANGE_MANIFEST_SUFFIX = ".model-exchanges.json"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"


# ---------------------------------------------------------------------------
# Manifest persistence
# ---------------------------------------------------------------------------


def configuration_identity(
    configuration: ModelConfiguration, prompt_digest: str, endpoint_host: str | None
) -> str:
    """Hash only stable model, prompt and endpoint identity fields."""
    payload = {
        "model_configuration_digest": configuration.canonical_digest(),
        "prompt_digest": prompt_digest,
        "endpoint_host": endpoint_host,
        "provider_label": configuration.provider,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def model_exchange_manifest_id(scenario_id: str, run_id: str) -> str:
    """Return the manifest identifier binding exchanges to one scenario run."""
    return f"{scenario_id}__{run_id}"


def model_exchange_manifest_path(
    directory: Path, scenario_id: str, run_id: str, configuration_digest: str
) -> Path:
    """Bind a manifest name to both the run and its model configuration."""
    return directory / (
        f"{model_exchange_manifest_id(scenario_id, run_id)}__"
        f"{configuration_digest[:12]}{MODEL_EXCHANGE_MANIFEST_SUFFIX}"
    )


def write_model_exchange_manifest(path: Path, manifest: ModelExchangeManifest) -> None:
    """Persist a manifest as canonical, human-readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_model_exchange_manifest(path: Path) -> ModelExchangeManifest:
    """Load a manifest, failing closed when it is missing or malformed."""
    if not path.is_file():
        raise ModelReplayMissingExchangeError(
            f"Model exchange manifest not found: {path.name}. Record it first with "
            "--model-mode record --allow-live-model."
        )
    try:
        return ModelExchangeManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ModelReplayManifestInvalidError(
            f"Model exchange manifest {path.name} is not a valid ModelExchangeManifest: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# OpenAI-compatible Chat Completions client
# ---------------------------------------------------------------------------


def _encode_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    encoded: list[dict[str, Any]] = []
    for tool in tools:
        function = dict(tool["function"])
        function["name"] = to_provider_tool_name(str(function["name"]))
        encoded.append({**tool, "function": function})
    return encoded


def tool_schema_digest(tools: list[dict[str, Any]]) -> str:
    """Hash the canonical provider-facing tool list sent over the wire."""
    raw = json.dumps(_encode_tools(tools), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _encode_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    encoded: list[dict[str, Any]] = []
    for message in messages:
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            encoded.append(message)
            continue
        wire_calls = []
        for call in tool_calls:
            function = dict(call["function"])
            function["name"] = to_provider_tool_name(str(function["name"]))
            wire_calls.append({**call, "function": function})
        encoded.append({**message, "tool_calls": wire_calls})
    return encoded


class OpenAIChatCompletionsClient:
    """Async client for OpenAI-compatible Chat Completions endpoints.

    Works against OpenAI and any compatible server (Ollama, vLLM, OpenRouter)
    via ``base_url``.  ``record`` mode writes one manifest per run into
    ``record_dir``; ``live`` mode keeps exchanges only for the run's
    :meth:`end_run` result.  A fresh SDK client is opened per run because
    benchmark cases run on separate event loops; an injected ``http_client``
    is owned by the caller and never closed here.
    """

    def __init__(
        self,
        *,
        api_key: str,
        mode: NetworkModelMode = "record",
        record_dir: Path | None = None,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if mode == "record" and record_dir is None:
            raise ModelClientConfigurationError(
                "Model record mode requires an output directory for exchange manifests."
            )
        self._mode: NetworkModelMode = mode
        self._record_dir = record_dir
        self._api_key = api_key
        self._base_url = base_url
        self._http_client = http_client
        self._client: openai.AsyncOpenAI | None = None
        self._exchange_history: list[ModelExchange] = []
        self._run: tuple[str, str, ModelConfiguration] | None = None
        self._prompt_digest: str | None = None

    def __repr__(self) -> str:
        # Never expose the API key through reprs or logs.
        return f"OpenAIChatCompletionsClient(mode={self._mode!r}, host={self.endpoint_host!r})"

    @property
    def provider(self) -> str:
        return "openai-chat-completions"

    @property
    def endpoint_host(self) -> str | None:
        """Expose the endpoint hostname, never credentials, path or query."""
        return urlsplit(self._base_url or "https://api.openai.com/v1").hostname

    @property
    def exchange_history(self) -> list[ModelExchange]:
        return list(self._exchange_history)

    def begin_run(
        self, *, scenario_id: str, run_id: str, configuration: ModelConfiguration,
        prompt_digest: str | None = None,
    ) -> None:
        self._exchange_history.clear()
        self._run = (scenario_id, run_id, configuration)
        self._prompt_digest = prompt_digest
        self._client = openai.AsyncOpenAI(
            api_key=self._api_key, base_url=self._base_url, http_client=self._http_client
        )

    async def end_run(self) -> ModelExchangeManifest:
        if self._run is None or self._client is None:
            raise RuntimeError("end_run() called without begin_run().")
        scenario_id, run_id, configuration = self._run
        client = self._client
        self._run = None
        self._client = None
        if self._http_client is None:
            await client.close()
        prompt_digest = (
            self._prompt_digest if self._prompt_digest is not None else (
                self._exchange_history[0].request.prompt_digest if self._exchange_history else ""
            )
        )
        digest = configuration_identity(configuration, prompt_digest, self.endpoint_host)
        manifest = ModelExchangeManifest(
            manifest_id=model_exchange_manifest_id(scenario_id, run_id),
            model_configuration=configuration,
            exchanges=list(self._exchange_history),
            endpoint_host=self.endpoint_host,
            configuration_digest=digest,
        )
        payload = manifest.model_dump(mode="json")
        if redact_secrets(payload, [self._api_key]) != payload:
            raise ModelProviderError(
                ModelError(
                    error_type=ModelErrorType.INVALID_RESPONSE,
                    message="Refusing to persist model exchanges containing a secret.",
                )
            )
        if self._mode == "record" and self._record_dir is not None:
            write_model_exchange_manifest(
                model_exchange_manifest_path(self._record_dir, scenario_id, run_id, digest), manifest
            )
        return manifest

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        """Send the request over the wire and record the exchange."""
        if self._client is None:
            raise RuntimeError("create_completion() called outside begin_run()/end_run().")
        config = request.model_configuration
        kwargs: dict[str, Any] = {
            "model": request.model_id,
            "messages": _encode_messages(request.messages),
            "temperature": config.temperature,
        }
        if config.max_tokens is not None:
            kwargs["max_tokens"] = config.max_tokens
        if config.top_p is not None:
            kwargs["top_p"] = config.top_p
        if request.tools:
            kwargs["tools"] = _encode_tools(request.tools)

        try:
            raw_resp = await self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise ModelProviderError(
                ModelError(
                    error_type=ModelErrorType.AUTHENTICATION,
                    message="Model provider authentication failed",
                    safe_details={"type": "AuthenticationError"},
                )
            ) from exc
        except openai.RateLimitError as exc:
            raise ModelProviderError(
                ModelError(
                    error_type=ModelErrorType.RATE_LIMIT,
                    message="Model provider rate limit exceeded",
                    safe_details={"type": "RateLimitError"},
                    retryable=True,
                )
            ) from exc
        except openai.APITimeoutError as exc:
            raise ModelProviderError(
                ModelError(
                    error_type=ModelErrorType.TIMEOUT,
                    message="Model provider request timed out",
                    safe_details={"type": "APITimeoutError"},
                    retryable=True,
                )
            ) from exc
        except openai.APIConnectionError as exc:
            raise ModelProviderError(
                ModelError(
                    error_type=ModelErrorType.CONNECTION_FAILURE,
                    message="Model provider connection failed",
                    safe_details={"type": "APIConnectionError"},
                    retryable=True,
                )
            ) from exc
        except openai.OpenAIError as exc:
            raise ModelProviderError(
                ModelError(
                    error_type=ModelErrorType.PROVIDER_UNAVAILABLE,
                    message="Model provider error",
                    safe_details={"type": type(exc).__name__},
                )
            ) from exc

        if not raw_resp.choices:
            raise ModelProviderError(
                ModelError(
                    error_type=ModelErrorType.INVALID_RESPONSE,
                    message="Model provider returned no choices",
                )
            )
        choice = raw_resp.choices[0]
        msg = choice.message

        tool_calls: list[ModelToolCall] = []
        for tc in msg.tool_calls or []:
            function = getattr(tc, "function", None)
            if function is None:
                raise ModelProviderError(
                    ModelError(
                        error_type=ModelErrorType.INVALID_TOOL_CALL,
                        message=f"Model tool call {tc.id} is not a function call",
                    )
                )
            internal_name = from_provider_tool_name(function.name)
            arguments_error: str | None = None
            try:
                args = loads_strict(
                    function.arguments,
                    max_bytes=1_000_000,
                    max_depth=64,
                    source="model tool arguments",
                )
                if not isinstance(args, dict):
                    arguments_error = "Tool arguments must be a JSON object"
                    args = {}
            except StrictJSONError:
                arguments_error = "Tool arguments must be strict JSON"
                args = {}
            tool_calls.append(
                ModelToolCall(
                    call_id=tc.id,
                    tool_name=internal_name,
                    arguments=args,
                    raw_arguments=function.arguments,
                    arguments_error=arguments_error,
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
        self._exchange_history.append(
            ModelExchange(
                turn_index=request.turn_index,
                request=request,
                response=response,
                request_fingerprint=request.canonical_fingerprint(),
                response_digest=response.canonical_digest(),
            )
        )
        return response


# ---------------------------------------------------------------------------
# Offline replay client
# ---------------------------------------------------------------------------


class ReplayModelClient:
    """Strict replay model client with SHA-256 fingerprint verification and zero network calls.

    Construct it from one manifest (or bare exchanges) to replay a single run,
    or with :meth:`from_directory` to load each run's manifest by scenario and
    run identity at :meth:`begin_run`.
    """

    def __init__(
        self,
        manifest_or_exchanges: ModelExchangeManifest | list[ModelExchange],
    ) -> None:
        self._directory: Path | None = None
        self._manifest: ModelExchangeManifest | None = None
        self._exchanges: list[ModelExchange] = []
        self._fingerprint_index: dict[str, ModelExchange] = {}
        self._exchange_history: list[ModelExchange] = []
        self._run: tuple[str, str, ModelConfiguration] | None = None
        if isinstance(manifest_or_exchanges, ModelExchangeManifest):
            self._manifest = manifest_or_exchanges
            self._index(list(manifest_or_exchanges.exchanges))
        else:
            self._index(list(manifest_or_exchanges))

    @classmethod
    def from_directory(cls, directory: Path) -> ReplayModelClient:
        """Replay per-run manifests stored under *directory* by ``record`` mode."""
        if not directory.is_dir():
            raise ModelClientConfigurationError(
                f"Model replay directory not found: {directory.name}"
            )
        client = cls([])
        client._directory = directory
        return client

    def _index(self, exchanges: list[ModelExchange]) -> None:
        self._exchanges = exchanges
        self._fingerprint_index = {}
        for ex in exchanges:
            fp = ex.request_fingerprint
            if fp in self._fingerprint_index:
                raise ModelReplayManifestInvalidError(
                    f"Duplicate request fingerprint {fp!r} in model exchange manifest."
                )
            self._fingerprint_index[fp] = ex

    @property
    def provider(self) -> str:
        return "replay"

    @property
    def endpoint_host(self) -> str | None:
        if self._manifest is not None:
            return self._manifest.endpoint_host
        if self._directory is not None:
            return _replay_directory_host(self._directory)
        return None

    @property
    def exchange_history(self) -> list[ModelExchange]:
        return list(self._exchange_history)

    def begin_run(
        self, *, scenario_id: str, run_id: str, configuration: ModelConfiguration,
        prompt_digest: str | None = None,
    ) -> None:
        self._exchange_history.clear()
        if self._directory is not None:
            candidates = [
                load_model_exchange_manifest(path)
                for path in self._directory.glob(
                    f"{model_exchange_manifest_id(scenario_id, run_id)}__*"
                    f"{MODEL_EXCHANGE_MANIFEST_SUFFIX}"
                )
            ]
            if not candidates:
                raise ModelReplayMissingExchangeError("Model exchange manifest not found.")
            matching = [
                m for m in candidates
                if m.model_configuration == configuration and (
                    prompt_digest is None or not m.exchanges
                    or m.exchanges[0].request.prompt_digest == prompt_digest
                )
            ]
            if len(matching) > 1:
                raise ModelReplayManifestInvalidError(
                    "Multiple model manifests match this run; select an explicit manifest."
                )
            manifest = matching[0] if matching else candidates[0]
            expected_id = model_exchange_manifest_id(scenario_id, run_id)
            if manifest.manifest_id != expected_id:
                raise ModelReplayManifestInvalidError(
                    f"Model exchange manifest id {manifest.manifest_id!r} does not match "
                    f"run {expected_id!r}."
                )
            self._manifest = manifest
            self._index(list(manifest.exchanges))
        if self._manifest is not None and self._manifest.model_configuration != configuration:
            raise ModelReplayFingerprintMismatchError(
                "Replay model configuration mismatch: the manifest was recorded with "
                f"{self._manifest.model_configuration.model_dump()} but the agent is "
                f"configured with {configuration.model_dump()}."
            )
        self._run = (scenario_id, run_id, configuration)

    async def end_run(self) -> ModelExchangeManifest:
        if self._run is None:
            raise RuntimeError("end_run() called without begin_run().")
        scenario_id, run_id, configuration = self._run
        self._run = None
        manifest_id = (
            self._manifest.manifest_id
            if self._manifest is not None
            else model_exchange_manifest_id(scenario_id, run_id)
        )
        return ModelExchangeManifest(
            manifest_id=manifest_id,
            model_configuration=configuration,
            exchanges=list(self._exchange_history),
            endpoint_host=self.endpoint_host,
            configuration_digest=(
                self._manifest.configuration_digest if self._manifest is not None else None
            ),
        )

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        """Replay recorded response for request. Zero network calls performed."""
        actual_fingerprint = request.canonical_fingerprint()
        recorded_exchange = self._fingerprint_index.get(actual_fingerprint)

        if recorded_exchange is None:
            turn_index = request.turn_index
            if turn_index < len(self._exchanges):
                candidate = self._exchanges[turn_index]
                raise ModelReplayFingerprintMismatchError(
                    f"Replay fingerprint mismatch at turn {turn_index}.\n"
                    f"Expected: {candidate.request_fingerprint}\n"
                    f"Actual:   {actual_fingerprint}"
                )
            raise ModelReplayMissingExchangeError(
                f"Replay error: No recorded model exchange for fingerprint "
                f"{actual_fingerprint} (turn {turn_index})"
            )

        computed_response_digest = recorded_exchange.response.canonical_digest()
        if computed_response_digest != recorded_exchange.response_digest:
            raise ModelReplayResponseDigestMismatchError(
                f"Recorded model response canonical digest mismatch for turn "
                f"{recorded_exchange.turn_index}.\n"
                f"Expected: {recorded_exchange.response_digest}\n"
                f"Computed: {computed_response_digest}\n"
                "The recorded model response has been altered or tampered with."
            )

        self._exchange_history.append(recorded_exchange)
        return recorded_exchange.response


# ---------------------------------------------------------------------------
# Settings-driven construction (CLI and benchmark registry)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelAgentSettings:
    """Operator-supplied configuration for the model-driven agent.

    ``replay`` (the default) is fully offline.  ``record`` and ``live`` reach the
    network and require both ``allow_live_model`` and the API key environment
    variable named by ``api_key_env``.
    """

    mode: ModelMode = "replay"
    model_configuration: ModelConfiguration = field(default_factory=ModelConfiguration)
    replay_manifest: Path | None = None
    replay_dir: Path | None = None
    record_dir: Path | None = None
    allow_live_model: bool = False
    base_url: str | None = None
    api_key_env: str = DEFAULT_API_KEY_ENV


def _replay_directory_host(directory: Path) -> str | None:
    hosts = {
        load_model_exchange_manifest(path).endpoint_host
        for path in directory.glob(f"*{MODEL_EXCHANGE_MANIFEST_SUFFIX}")
    }
    if len(hosts) > 1:
        raise ModelClientConfigurationError(
            "Replay directory contains multiple endpoint hosts; select an explicit manifest."
        )
    return hosts.pop() if hosts else None


def model_agent_configuration_digest(settings: ModelAgentSettings) -> str:
    """Compute registry identity without constructing a network or replay client."""
    host: str | None = None
    if settings.mode != "replay":
        host = urlsplit(settings.base_url or "https://api.openai.com/v1").hostname
    elif settings.replay_manifest is not None:
        host = load_model_exchange_manifest(settings.replay_manifest).endpoint_host
    elif settings.replay_dir is not None:
        host = _replay_directory_host(settings.replay_dir)
    return configuration_identity(
        settings.model_configuration, get_default_prompt_policy().canonical_digest(), host
    )


def build_model_client(
    settings: ModelAgentSettings,
    *,
    environ: Mapping[str, str] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> ModelClient:
    """Build the model client described by *settings*, failing closed on unsafe config."""
    if settings.mode == "replay":
        if settings.replay_manifest is not None:
            return ReplayModelClient(load_model_exchange_manifest(settings.replay_manifest))
        if settings.replay_dir is not None:
            return ReplayModelClient.from_directory(settings.replay_dir)
        raise ModelClientConfigurationError(
            "Model replay mode requires a recorded manifest "
            "(--model-replay-manifest PATH or --model-replay-dir DIR)."
        )

    if not settings.allow_live_model:
        raise ModelClientConfigurationError(
            f"Model mode '{settings.mode}' calls a network model and requires the explicit "
            "--allow-live-model flag."
        )
    env = os.environ if environ is None else environ
    api_key = env.get(settings.api_key_env)
    if not api_key:
        raise ModelClientConfigurationError(
            f"Model mode '{settings.mode}' requires the {settings.api_key_env} "
            "environment variable to be set."
        )
    if settings.mode == "record" and settings.record_dir is None:
        raise ModelClientConfigurationError(
            "Model record mode requires an output directory for exchange manifests (--output)."
        )
    return OpenAIChatCompletionsClient(
        api_key=api_key,
        mode=settings.mode,
        record_dir=settings.record_dir,
        base_url=settings.base_url,
        http_client=http_client,
    )


__all__ = [
    "DEFAULT_API_KEY_ENV",
    "MODEL_EXCHANGE_MANIFEST_SUFFIX",
    "ModelAgentSettings",
    "ModelMode",
    "OpenAIChatCompletionsClient",
    "ReplayModelClient",
    "build_model_client",
    "configuration_identity",
    "model_agent_configuration_digest",
    "load_model_exchange_manifest",
    "model_exchange_manifest_id",
    "model_exchange_manifest_path",
    "write_model_exchange_manifest",
]

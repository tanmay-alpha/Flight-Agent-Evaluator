"""Typed provider errors."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Base provider error
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base exception for all provider errors."""

    def __init__(
        self,
        error_code: str,
        provider: str,
        safe_message: str,
        retryable: bool = False,
        correlation_id: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.provider = provider
        self.retryable = retryable
        self.safe_message = safe_message
        self.correlation_id = correlation_id or str(uuid.uuid4())
        super().__init__(safe_message)


# ---------------------------------------------------------------------------
# ProviderContractModel - for structured error data via Pydantic
# ---------------------------------------------------------------------------


class ProviderErrorContract(BaseModel):
    """Structured representation of a provider error for serialization."""

    error_code: str
    provider: str
    safe_message: str
    retryable: bool = False
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Specific provider errors
# ---------------------------------------------------------------------------


class ProviderUnavailableError(ProviderError):
    def __init__(self, *, provider: str, safe_message: str) -> None:
        super().__init__(
            error_code="provider_unavailable",
            provider=provider,
            safe_message=safe_message,
            retryable=True,
        )


class ProviderTimeoutError(ProviderError):
    def __init__(self, *, provider: str, safe_message: str) -> None:
        super().__init__(
            error_code="provider_timeout",
            provider=provider,
            safe_message=safe_message,
            retryable=True,
        )


class ProviderRateLimitError(ProviderError):
    def __init__(self, *, provider: str, safe_message: str) -> None:
        super().__init__(
            error_code="provider_rate_limit",
            provider=provider,
            safe_message=safe_message,
            retryable=True,
        )


class ProviderAuthenticationError(ProviderError):
    def __init__(self, *, provider: str, safe_message: str) -> None:
        super().__init__(
            error_code="provider_authentication",
            provider=provider,
            safe_message=safe_message,
            retryable=False,
        )


class ProviderDataNotFoundError(ProviderError):
    def __init__(self, *, provider: str, safe_message: str) -> None:
        super().__init__(
            error_code="provider_data_not_found",
            provider=provider,
            safe_message=safe_message,
            retryable=False,
        )


class ProviderInvalidResponseError(ProviderError):
    def __init__(self, *, provider: str, safe_message: str) -> None:
        super().__init__(
            error_code="provider_invalid_response",
            provider=provider,
            safe_message=safe_message,
            retryable=False,
        )


class ProviderQuotaExhaustedError(ProviderError):
    def __init__(self, *, provider: str, safe_message: str) -> None:
        super().__init__(
            error_code="provider_quota_exhausted",
            provider=provider,
            safe_message=safe_message,
            retryable=False,
        )

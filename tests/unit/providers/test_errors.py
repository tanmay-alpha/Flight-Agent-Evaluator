"""Tests for the provider errors hierarchy."""

from __future__ import annotations

import uuid

import pytest

from flight_agent_evaluator.providers.errors import (
    ProviderAuthenticationError,
    ProviderDataNotFoundError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class TestProviderErrorBase:
    def test_is_exception(self) -> None:
        err = ProviderError(error_code="test", provider="p", safe_message="msg")
        assert isinstance(err, Exception)

    def test_default_fields(self) -> None:
        err = ProviderError(error_code="test", provider="p", safe_message="msg")
        assert err.error_code == "test"
        assert err.provider == "p"
        assert err.safe_message == "msg"
        assert err.retryable is False
        assert err.correlation_id is not None

    def test_correlation_id_generated(self) -> None:
        err = ProviderError(error_code="test", provider="p", safe_message="msg")
        # Should be a valid UUID string
        uuid.UUID(err.correlation_id)

    def test_custom_correlation_id(self) -> None:
        cid = "abc-123"
        err = ProviderError(error_code="test", provider="p", safe_message="msg", correlation_id=cid)
        assert err.correlation_id == "abc-123"

    def test_is_retryable(self) -> None:
        err = ProviderError(error_code="test", provider="p", safe_message="msg", retryable=True)
        assert err.retryable is True


class TestSpecificErrors:
    @pytest.mark.parametrize(
        "cls, expected_code, expected_retryable",
        [
            (ProviderUnavailableError, "provider_unavailable", True),
            (ProviderTimeoutError, "provider_timeout", True),
            (ProviderRateLimitError, "provider_rate_limit", True),
            (ProviderAuthenticationError, "provider_authentication", False),
            (ProviderDataNotFoundError, "provider_data_not_found", False),
            (ProviderInvalidResponseError, "provider_invalid_response", False),
            (ProviderQuotaExhaustedError, "provider_quota_exhausted", False),
        ],
    )
    def test_error_properties(self, cls, expected_code, expected_retryable) -> None:
        err = cls(provider="p", safe_message="msg")
        assert err.error_code == expected_code
        assert err.retryable == expected_retryable
        assert isinstance(err, ProviderError)

    def test_catch_as_base(self) -> None:
        try:
            raise ProviderUnavailableError(provider="p", safe_message="msg")
        except ProviderError as e:
            assert e.error_code == "provider_unavailable"

    def test_catch_specific(self) -> None:
        with pytest.raises(ProviderDataNotFoundError):
            raise ProviderDataNotFoundError(provider="p", safe_message="not found")

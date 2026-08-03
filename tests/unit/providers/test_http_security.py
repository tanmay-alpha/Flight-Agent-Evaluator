"""Unit tests for HTTP security layer, URL validation, and credential sanitization."""

from __future__ import annotations

import pytest

from flight_agent_evaluator.providers.errors import ProviderError
from flight_agent_evaluator.providers.http import (
    HTTPResponse,
    SecureHTTPClient,
    sanitize_credentials,
    sanitize_url,
)


class TestCredentialSanitization:
    def test_sanitize_authorization_header(self):
        text = "Request with Authorization: Bearer secret_token_12345 in header"
        sanitized = sanitize_credentials(text)
        assert "secret_token_12345" not in sanitized
        assert "Authorization: [REDACTED]" in sanitized

    def test_sanitize_api_key_query_param(self):
        url = "https://api.aviationstack.com/v1/flights?access_key=my_secret_key_9999&flight_iata=AA100"
        sanitized = sanitize_url(url)
        assert "my_secret_key_9999" not in sanitized
        assert "access_key=[REDACTED]" in sanitized

    def test_sanitize_basic_auth_url(self):
        url = "https://user:password123@opensky-network.org/api/states/all"
        sanitized = sanitize_url(url)
        assert "password123" not in sanitized
        assert "user:[REDACTED]@" in sanitized

    def test_sanitize_generic_secret_patterns(self):
        text = "x-api-key: super_secret_val_123; api_key=another_secret_321"
        sanitized = sanitize_credentials(text)
        assert "super_secret_val_123" not in sanitized
        assert "another_secret_321" not in sanitized


class TestSecureHTTPClientValidation:
    def test_reject_unallowed_host(self):
        client = SecureHTTPClient(allowed_hosts=("api.aviationstack.com",))
        with pytest.raises(ProviderError) as exc_info:
            client.get("https://untrusted-host.com/data")
        assert "Host not allowed" in str(exc_info.value)
        assert exc_info.value.error_code == "security_host_denied"

    def test_reject_non_get_methods(self):
        client = SecureHTTPClient(allowed_hosts=("api.aviationstack.com",))
        with pytest.raises(ProviderError) as exc_info:
            client.request("POST", "https://api.aviationstack.com/v1/flights", body=b"data")
        assert "Method not allowed" in str(exc_info.value)
        assert exc_info.value.error_code == "security_method_denied"

    def test_reject_non_https_if_enforced(self):
        client = SecureHTTPClient(allowed_hosts=("api.aviationstack.com",), require_tls=True)
        with pytest.raises(ProviderError) as exc_info:
            client.get("http://api.aviationstack.com/v1/flights")
        assert "HTTPS required" in str(exc_info.value)

    def test_mock_transport_response(self):
        def mock_handler(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            assert method == "GET"
            assert "secret123" in url  # Real URL passed internally to transport
            return HTTPResponse(
                status_code=200, headers={"content-type": "application/json"}, body=b'{"data": []}'
            )

        client = SecureHTTPClient(allowed_hosts=("api.aviationstack.com",), transport=mock_handler)
        resp = client.get("https://api.aviationstack.com/v1/flights?access_key=secret123")
        assert resp.status_code == 200
        assert resp.json() == {"data": []}

    def test_default_transport_success(self, monkeypatch):
        import io
        import urllib.request

        class DummyResponse(io.BytesIO):
            status = 200
            headers = {"Content-Type": "application/json"}

            def read(self, *args, **kwargs):
                return b'{"status": "ok"}'

        def dummy_urlopen(req, timeout):
            return DummyResponse()

        monkeypatch.setattr(urllib.request, "urlopen", dummy_urlopen)
        client = SecureHTTPClient(allowed_hosts=("api.aviationstack.com",))
        resp = client.get("https://api.aviationstack.com/v1/flights")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_default_transport_httperror(self, monkeypatch):
        import urllib.error
        import urllib.request
        from typing import Any, cast

        def dummy_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                url="https://api.aviationstack.com/v1/flights",
                code=401,
                msg="Unauthorized",
                hdrs=cast(Any, {"Content-Type": "application/json"}),
                fp=None,
            )

        monkeypatch.setattr(urllib.request, "urlopen", dummy_urlopen)
        client = SecureHTTPClient(allowed_hosts=("api.aviationstack.com",))
        resp = client.get("https://api.aviationstack.com/v1/flights")
        assert resp.status_code == 401

    def test_default_transport_timeout_mapped(self):
        def timeout_handler(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            raise TimeoutError("Connection timed out")

        client = SecureHTTPClient(
            allowed_hosts=("api.aviationstack.com",), transport=timeout_handler
        )
        with pytest.raises(ProviderError) as exc_info:
            client.get("https://api.aviationstack.com/v1/flights?access_key=secret_123")
        assert exc_info.value.error_code == "provider_timeout"
        assert "secret_123" not in str(exc_info.value)
        assert "access_key=[REDACTED]" in str(exc_info.value)

    def test_default_transport_generic_error_mapped(self):
        def generic_error_handler(
            method: str, url: str, headers: dict[str, str], body: bytes | None
        ) -> HTTPResponse:
            raise RuntimeError(
                "Connection reset by peer with Authorization: Bearer secret_token_abc"
            )

        client = SecureHTTPClient(
            allowed_hosts=("api.aviationstack.com",), transport=generic_error_handler
        )
        with pytest.raises(ProviderError) as exc_info:
            client.get("https://api.aviationstack.com/v1/flights")
        assert exc_info.value.error_code == "provider_unavailable"
        assert "secret_token_abc" not in str(exc_info.value)
        assert "[REDACTED]" in str(exc_info.value)

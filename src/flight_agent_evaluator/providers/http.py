"""Secure read-only HTTP transport and credential sanitization layer."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flight_agent_evaluator.providers.errors import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

# Sensitive patterns for credential redaction
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+\/=]+", re.IGNORECASE)
_AUTH_HEADER_PATTERN = re.compile(r"(Authorization:\s*)[^\r\n,;]+", re.IGNORECASE)
_QUERY_CREDENTIAL_PATTERN = re.compile(
    r"((?:access_key|api_key|apikey|token|secret|password|auth)=)[^&\s]+",
    re.IGNORECASE,
)
_HEADER_CREDENTIAL_PATTERN = re.compile(
    r"((?:x-api-key|x-auth-token|api-key|access-key):\s*)[^\r\n,;]+",
    re.IGNORECASE,
)
_USERINFO_URL_PATTERN = re.compile(r"(https?://)([^:]+):([^@]+)@", re.IGNORECASE)


def sanitize_credentials(text: str) -> str:
    """Sanitise sensitive credential strings from error messages or logs."""
    if not text:
        return ""
    result = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    result = _AUTH_HEADER_PATTERN.sub(r"\1[REDACTED]", result)
    result = _QUERY_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]", result)
    result = _HEADER_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]", result)
    return result


def sanitize_url(url: str) -> str:
    """Sanitise basic auth and sensitive query parameters from a URL."""
    if not url:
        return ""
    result = _USERINFO_URL_PATTERN.sub(r"\1\2:[REDACTED]@", url)
    result = _QUERY_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]", result)
    return result


@dataclass(frozen=True)
class HTTPResponse:
    """HTTP response payload container."""

    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        """Parse body as JSON."""
        return json.loads(self.body.decode("utf-8"))


TransportCallable = Callable[[str, str, dict[str, str], bytes | None], HTTPResponse]


class SecureHTTPClient:
    """Read-only HTTP client enforcing domain whitelist, TLS, and credential scrub."""

    def __init__(
        self,
        allowed_hosts: tuple[str, ...] | list[str],
        timeout_seconds: float = 10.0,
        require_tls: bool = True,
        transport: TransportCallable | None = None,
    ) -> None:
        self.allowed_hosts = tuple(h.lower() for h in allowed_hosts)
        self.timeout_seconds = timeout_seconds
        self.require_tls = require_tls
        self._transport = transport or self._default_transport

    def get(self, url: str, headers: dict[str, str] | None = None) -> HTTPResponse:
        """Perform a read-only GET request."""
        return self.request("GET", url, headers=headers, body=None)

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> HTTPResponse:
        """Execute a validated HTTP request."""
        upper_method = method.upper()
        if upper_method != "GET":
            raise ProviderError(
                error_code="security_method_denied",
                provider="http_client",
                safe_message=f"Method not allowed: {upper_method}. Providers are strictly read-only GET.",
                retryable=False,
            )

        parsed = urllib.parse.urlparse(url)
        if self.require_tls and parsed.scheme.lower() != "https":
            raise ProviderError(
                error_code="security_tls_required",
                provider="http_client",
                safe_message=f"HTTPS required for provider API call, got scheme '{parsed.scheme}'",
                retryable=False,
            )

        host = (parsed.hostname or "").lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise ProviderError(
                error_code="security_host_denied",
                provider="http_client",
                safe_message=f"Host not allowed: '{host}'. Allowed hosts: {self.allowed_hosts}",
                retryable=False,
            )

        req_headers = dict(headers or {})
        try:
            return self._transport(upper_method, url, req_headers, body)
        except ProviderError:
            raise
        except TimeoutError as exc:
            clean_url = sanitize_url(url)
            raise ProviderTimeoutError(
                provider="http_client",
                safe_message=f"Request to {clean_url} timed out after {self.timeout_seconds}s",
            ) from exc
        except Exception as exc:
            clean_url = sanitize_url(url)
            clean_err = sanitize_credentials(str(exc))
            raise ProviderUnavailableError(
                provider="http_client",
                safe_message=f"HTTP request to {clean_url} failed: {clean_err}",
            ) from exc

    def _default_transport(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> HTTPResponse:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                resp_body = resp.read()
                return HTTPResponse(
                    status_code=resp.status,
                    headers=resp_headers,
                    body=resp_body,
                )
        except urllib.error.HTTPError as exc:
            resp_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
            resp_body = exc.read() if hasattr(exc, "read") else b""
            return HTTPResponse(
                status_code=exc.code,
                headers=resp_headers,
                body=resp_body,
            )

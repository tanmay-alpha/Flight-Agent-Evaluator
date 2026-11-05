"""Typed exceptions for model execution and model replay integrity."""

from __future__ import annotations

from flight_agent_evaluator.contracts.model import ModelError


class ModelReplayError(RuntimeError):
    """Base exception for model replay failures."""


class ModelReplayIntegrityError(ModelReplayError):
    """Raised when recorded model exchange or response fails cryptographic integrity verification."""


class ModelReplayResponseDigestMismatchError(ModelReplayIntegrityError):
    """Raised when the computed canonical digest of a recorded response does not match the stored response_digest."""


class ModelReplayFingerprintMismatchError(ModelReplayIntegrityError):
    """Raised when incoming request fingerprint does not match recorded request fingerprint."""


class ModelReplayMissingExchangeError(ModelReplayError):
    """Raised when no recorded model exchange matches the requested turn or fingerprint."""


class ModelReplayManifestInvalidError(ModelReplayIntegrityError):
    """Raised when a model exchange manifest has duplicate fingerprints or invalid digests."""


class ModelClientConfigurationError(ValueError):
    """Raised when a model client is requested with unsafe or incomplete configuration."""


class ModelProviderError(RuntimeError):
    """Raised when the model provider call fails; carries only a safe, typed error."""

    def __init__(self, error: ModelError) -> None:
        super().__init__(error.message)
        self.error = error

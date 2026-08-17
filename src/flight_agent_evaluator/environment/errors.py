"""Typed exceptions for the simulated transactional airline environment."""

from __future__ import annotations


class EnvironmentError(Exception):
    """Base exception for all simulated airline environment errors."""


class StateTransitionError(EnvironmentError):
    """Raised when an invalid state machine transition is attempted."""


class OwnershipMismatchError(EnvironmentError):
    """Raised when related resources do not belong to the same booking scope."""


class UnknownOfferError(EnvironmentError):
    """Raised when a requested synthetic offer is not environment-owned."""


class OfferUnavailableError(EnvironmentError):
    """Raised when an authoritative offer is expired or unavailable."""


class TransactionConflictError(EnvironmentError):
    """Raised when a competing mutation cannot safely be committed."""


class ApprovalError(EnvironmentError):
    """Base exception for approval-related failures."""


class ApprovalMissingError(ApprovalError):
    """Raised when a sensitive mutation is attempted without an approval ID."""


class ApprovalNotFoundError(ApprovalError):
    """Raised when the specified approval ID does not exist."""


class ApprovalExpiredError(ApprovalError):
    """Raised when an approval is present but has expired."""


class ApprovalScopeMismatchError(ApprovalError):
    """Raised when an approval's scope/payload_hash does not match the attempted mutation."""


class ApprovalDeniedError(ApprovalError):
    """Raised when an approval request was explicitly denied."""


class IdempotencyError(EnvironmentError):
    """Base exception for idempotency key failures."""


class IdempotencyConflictError(IdempotencyError):
    """Raised when an idempotency key is reused with a different request payload."""


class AmbiguousCommitError(EnvironmentError):
    """Raised when a transaction's commit status cannot be confirmed."""


class HoldExpiredError(EnvironmentError):
    """Raised when attempting to confirm a hold that has expired."""


class ResourceNotFoundError(EnvironmentError):
    """Raised when a booking, hold, or offer is not found."""

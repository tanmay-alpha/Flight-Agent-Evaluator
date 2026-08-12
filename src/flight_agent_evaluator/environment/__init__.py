"""Simulated transactional airline environment package."""

from flight_agent_evaluator.environment.approvals import ApprovalEngine
from flight_agent_evaluator.environment.contracts import (
    ENVIRONMENT_SCHEMA_VERSION,
    ApprovalRequest,
    ApprovalStatus,
    BookingRecord,
    BookingStatus,
    HoldRecord,
    HoldStatus,
    IdempotencyRecord,
    RebookingTransaction,
    TransactionStatus,
)
from flight_agent_evaluator.environment.engine import SimulatedAirlineEnvironment
from flight_agent_evaluator.environment.errors import (
    AmbiguousCommitError,
    ApprovalDeniedError,
    ApprovalError,
    ApprovalExpiredError,
    ApprovalMissingError,
    ApprovalNotFoundError,
    ApprovalScopeMismatchError,
    EnvironmentError,
    HoldExpiredError,
    IdempotencyConflictError,
    IdempotencyError,
    ResourceNotFoundError,
    StateTransitionError,
)
from flight_agent_evaluator.environment.idempotency import IdempotencyKeyRegistry

__all__ = [
    "ENVIRONMENT_SCHEMA_VERSION",
    "ApprovalEngine",
    "ApprovalRequest",
    "ApprovalStatus",
    "BookingRecord",
    "BookingStatus",
    "HoldRecord",
    "HoldStatus",
    "IdempotencyRecord",
    "RebookingTransaction",
    "SimulatedAirlineEnvironment",
    "TransactionStatus",
    "AmbiguousCommitError",
    "ApprovalDeniedError",
    "ApprovalError",
    "ApprovalExpiredError",
    "ApprovalMissingError",
    "ApprovalNotFoundError",
    "ApprovalScopeMismatchError",
    "EnvironmentError",
    "HoldExpiredError",
    "IdempotencyConflictError",
    "IdempotencyError",
    "ResourceNotFoundError",
    "StateTransitionError",
    "IdempotencyKeyRegistry",
]

"""Approval enforcement engine for sensitive state mutations.

Enforces that sensitive side-effects (e.g. confirming a flight rebooking):
1. Must reference a valid approval ID.
2. The approval must have status APPROVED.
3. The approval must not be expired relative to the virtual clock.
4. The approval scope (action_type, booking_reference) must match.
5. The approval payload_hash must match the SHA-256 canonical hash of the mutation payload.
"""

from __future__ import annotations

from datetime import datetime

from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.environment.contracts import (
    ApprovalRequest,
    ApprovalStatus,
)
from flight_agent_evaluator.environment.errors import (
    ApprovalExpiredError,
    ApprovalMissingError,
    ApprovalNotFoundError,
    ApprovalScopeMismatchError,
)


class ApprovalEngine:
    """In-memory approval registry and enforcement engine."""

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}

    def register_request(self, request: ApprovalRequest) -> None:
        """Register an approval request."""
        self._requests[request.approval_id] = request

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        """Look up an approval request by ID."""
        return self._requests.get(approval_id)

    def verify_approval_for_mutation(
        self,
        *,
        approval_id: str | None,
        action_type: str,
        booking_reference: str,
        mutation_payload: dict[str, object],
        current_time: datetime,
    ) -> ApprovalRequest:
        """Verify that a valid, non-expired, matching approval exists for a mutation.

        Args:
            approval_id: The approval ID supplied by the caller.
            action_type: Expected action type (e.g. 'rebook_flight').
            booking_reference: Expected booking reference.
            mutation_payload: Dict payload of the mutation parameters.
            current_time: Current virtual clock timestamp.

        Returns:
            The verified ApprovalRequest.

        Raises:
            ApprovalMissingError: If approval_id is None or empty.
            ApprovalNotFoundError: If approval_id is not in registry.
            ApprovalExpiredError: If approval is expired or status is EXPIRED.
            ApprovalScopeMismatchError: If action, booking_ref, or payload_hash mismatches.
        """
        if not approval_id:
            raise ApprovalMissingError(
                f"Action '{action_type}' is a sensitive mutation requiring an explicit approval_id."
            )

        req = self._requests.get(approval_id)
        if req is None:
            raise ApprovalNotFoundError(
                f"Approval ID '{approval_id}' was not found in the approval registry."
            )

        if req.status == ApprovalStatus.EXPIRED or req.is_expired(current_time):
            raise ApprovalExpiredError(
                f"Approval '{approval_id}' has expired (expires_at={req.expires_at.isoformat()})."
            )

        if req.status != ApprovalStatus.APPROVED:
            raise ApprovalScopeMismatchError(
                f"Approval '{approval_id}' status is '{req.status}', expected 'approved'."
            )

        if req.action_type != action_type:
            raise ApprovalScopeMismatchError(
                f"Approval action '{req.action_type}' does not match attempted action '{action_type}'."
            )

        if req.booking_reference != booking_reference:
            raise ApprovalScopeMismatchError(
                f"Approval booking reference '{req.booking_reference}' does not match '{booking_reference}'."
            )

        attempted_hash = canonical_hash(mutation_payload)
        if req.payload_hash != attempted_hash:
            raise ApprovalScopeMismatchError(
                f"Mutation payload hash '{attempted_hash[:8]}...' does not match "
                f"approved payload hash '{req.payload_hash[:8]}...'."
            )

        return req

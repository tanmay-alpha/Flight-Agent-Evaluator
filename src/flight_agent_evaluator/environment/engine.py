"""Simulated transactional airline environment engine.

In-memory, deterministic environment providing explicit state machine
transitions, approval enforcement, idempotency key registry, and
transaction logging.

No network calls, no real PII, no live API credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.contracts.base import Money
from flight_agent_evaluator.environment.approvals import ApprovalEngine
from flight_agent_evaluator.environment.contracts import (
    ApprovalRequest,
    ApprovalStatus,
    BookingRecord,
    BookingStatus,
    HoldRecord,
    HoldStatus,
    RebookingTransaction,
    TransactionStatus,
)
from flight_agent_evaluator.environment.errors import (
    HoldExpiredError,
    ResourceNotFoundError,
)
from flight_agent_evaluator.environment.fixtures import (
    get_default_approval_fixture,
    get_default_booking_fixture,
    get_default_hold_fixture,
)
from flight_agent_evaluator.environment.idempotency import IdempotencyKeyRegistry
from flight_agent_evaluator.environment.state import (
    validate_booking_transition,
    validate_hold_transition,
)
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory


@dataclass
class ApprovalDecisionPolicy:
    """Policy for determining scenario approval outcomes externally."""

    default_decision: ApprovalStatus = ApprovalStatus.APPROVED
    decisions_by_booking: dict[str, ApprovalStatus] = field(default_factory=dict)
    decisions_by_offer: dict[str, ApprovalStatus] = field(default_factory=dict)

    def get_decision(
        self, booking_reference: str, offer_id: str, action_type: str
    ) -> ApprovalStatus:
        del action_type
        if booking_reference in self.decisions_by_booking:
            return self.decisions_by_booking[booking_reference]
        if offer_id in self.decisions_by_offer:
            return self.decisions_by_offer[offer_id]
        return self.default_decision


@dataclass
class NotificationRecord:
    """Record of a simulated notification side-effect."""

    notification_id: str
    passenger_name: str
    message: str
    sent_at: datetime
    idempotency_key: str


class SimulatedAirlineEnvironment:
    """In-memory transactional airline environment engine."""

    def __init__(
        self,
        id_factory: DeterministicIdFactory | None = None,
        approval_policy: ApprovalDecisionPolicy | None = None,
    ) -> None:
        self.bookings: dict[str, BookingRecord] = {}
        self.holds: dict[str, HoldRecord] = {}
        self.approvals = ApprovalEngine()
        self.idempotency = IdempotencyKeyRegistry()
        self.transactions: list[RebookingTransaction] = []
        self.notifications: list[NotificationRecord] = []
        self.id_factory = id_factory or DeterministicIdFactory("sim_env", 1, 42)
        self.approval_policy = approval_policy or ApprovalDecisionPolicy()
        self._seq = 0

        # Load default synthetic fixtures
        default_booking = get_default_booking_fixture()
        self.bookings[default_booking.booking_reference] = default_booking
        default_hold = get_default_hold_fixture()
        self.holds[default_hold.hold_id] = default_hold
        default_approval = get_default_approval_fixture()
        self.approvals.register_request(default_approval)

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        raw_uuid = self.id_factory.next(prefix, self._seq)
        return f"{prefix}-{raw_uuid.hex[:8]}"

    def get_booking(self, booking_reference: str) -> BookingRecord:
        """Retrieve a booking record by reference."""
        booking = self.bookings.get(booking_reference)
        if booking is None:
            raise ResourceNotFoundError(
                f"Booking reference '{booking_reference}' was not found in environment."
            )
        return booking

    def place_hold(
        self,
        *,
        booking_reference: str,
        offer_id: str,
        flight_number: str,
        origin: str,
        destination: str,
        price_amount: float,
        price_currency: str = "USD",
        idempotency_key: str,
        current_time: datetime,
        hold_duration_minutes: int = 30,
    ) -> dict[str, Any]:
        """Place an inventory hold on an alternative flight offer.

        Idempotent: repeating with same key returns cached result.
        """
        payload = {
            "booking_reference": booking_reference,
            "offer_id": offer_id,
            "flight_number": flight_number,
            "origin": origin,
            "destination": destination,
            "price_amount": price_amount,
            "price_currency": price_currency,
        }

        # Check idempotency
        cached = self.idempotency.check_or_register(
            key=idempotency_key,
            tool_name="booking.hold_alternative",
            payload=payload,
            registered_at=current_time,
        )
        if cached is not None:
            return cached.result_payload

        # Validate booking exists
        booking = self.get_booking(booking_reference)

        # Generate hold ID deterministically
        hold_id = self._next_id("hold")
        expires_at = current_time + timedelta(minutes=hold_duration_minutes)
        hold = HoldRecord(
            hold_id=hold_id,
            booking_reference=booking_reference,
            offer_id=offer_id,
            flight_number=flight_number,
            origin=origin,
            destination=destination,
            price=Money(amount=price_amount, currency=price_currency),
            placed_at=current_time,
            expires_at=expires_at,
            status=HoldStatus.ACTIVE,
        )
        self.holds[hold_id] = hold

        # Update booking state
        validate_booking_transition(booking.status, BookingStatus.HOLD_PLACED)
        updated_booking = BookingRecord(
            booking_reference=booking.booking_reference,
            passenger_name=booking.passenger_name,
            current_flight_number=booking.current_flight_number,
            origin=booking.origin,
            destination=booking.destination,
            scheduled_departure=booking.scheduled_departure,
            status=BookingStatus.HOLD_PLACED,
            active_hold_id=hold_id,
            active_approval_id=booking.active_approval_id,
        )
        self.bookings[booking_reference] = updated_booking

        result = {
            "hold_id": hold_id,
            "status": "placed",
            "expires_at": expires_at.isoformat(),
            "flight_number": flight_number,
        }
        self.idempotency.save_result(
            key=idempotency_key,
            tool_name="booking.hold_alternative",
            payload=payload,
            result_payload=result,
            registered_at=current_time,
        )
        return result

    def request_approval(
        self,
        *,
        booking_reference: str,
        action_type: str,
        offer_id: str,
        reason: str,
        idempotency_key: str,
        current_time: datetime,
        hold_id: str | None = None,
        approval_duration_minutes: int = 60,
    ) -> dict[str, Any]:
        """Request supervisor/human approval for a sensitive mutation.

        Decision is determined externally by ApprovalDecisionPolicy (not by agent reason string).
        Idempotent: repeating with same key returns cached result.
        """
        payload = {
            "booking_reference": booking_reference,
            "action_type": action_type,
            "offer_id": offer_id,
            "reason": reason,
        }

        cached = self.idempotency.check_or_register(
            key=idempotency_key,
            tool_name="approval.request",
            payload=payload,
            registered_at=current_time,
        )
        if cached is not None:
            return cached.result_payload

        booking = self.get_booking(booking_reference)
        target_hold_id = hold_id or booking.active_hold_id or ""
        hold = self.holds.get(target_hold_id)

        if hold is not None:
            sensitive_payload: dict[str, Any] = {
                "action_type": action_type,
                "booking_reference": booking_reference,
                "hold_id": target_hold_id,
                "offer_id": offer_id,
                "flight_number": hold.flight_number,
                "price_amount": hold.price.amount,
                "price_currency": hold.price.currency,
            }
        else:
            sensitive_payload = {
                "action_type": action_type,
                "booking_reference": booking_reference,
                "hold_id": target_hold_id,
                "offer_id": offer_id,
            }

        approval_id = self._next_id("appr")
        expires_at = current_time + timedelta(minutes=approval_duration_minutes)
        p_hash = canonical_hash(sensitive_payload)

        # External approval decision policy
        status = self.approval_policy.get_decision(
            booking_reference=booking_reference,
            offer_id=offer_id,
            action_type=action_type,
        )

        req = ApprovalRequest(
            approval_id=approval_id,
            booking_reference=booking_reference,
            action_type=action_type,
            requested_offer_id=offer_id,
            payload_hash=p_hash,
            reason=reason,
            requested_at=current_time,
            expires_at=expires_at,
            status=status,
            decided_at=current_time if status == ApprovalStatus.APPROVED else None,
        )
        self.approvals.register_request(req)

        # Update booking
        self.bookings[booking_reference] = BookingRecord(
            booking_reference=booking.booking_reference,
            passenger_name=booking.passenger_name,
            current_flight_number=booking.current_flight_number,
            origin=booking.origin,
            destination=booking.destination,
            scheduled_departure=booking.scheduled_departure,
            status=booking.status,
            active_hold_id=booking.active_hold_id,
            active_approval_id=approval_id,
        )

        result = {
            "approval_id": approval_id,
            "status": status.value,
            "payload_hash": p_hash,
            "expires_at": expires_at.isoformat(),
        }
        self.idempotency.save_result(
            key=idempotency_key,
            tool_name="approval.request",
            payload=payload,
            result_payload=result,
            registered_at=current_time,
        )
        return result

    def confirm_rebooking(
        self,
        *,
        booking_reference: str,
        hold_id: str,
        approval_id: str,
        idempotency_key: str,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Confirm flight rebooking using a hold and a verified approval.

        Requires valid, non-expired approval whose payload_hash matches sensitive mutation payload.
        Idempotent: repeating with same key returns cached result.
        """
        hold = self.holds.get(hold_id)
        if hold is None:
            raise ResourceNotFoundError(f"Hold ID '{hold_id}' was not found.")

        payload_full: dict[str, Any] = {
            "action_type": "confirm_rebooking",
            "booking_reference": booking_reference,
            "hold_id": hold_id,
            "offer_id": hold.offer_id,
            "flight_number": hold.flight_number,
            "price_amount": hold.price.amount,
            "price_currency": hold.price.currency,
        }
        payload_minimal: dict[str, Any] = {
            "booking_reference": booking_reference,
            "hold_id": hold_id,
        }
        appr_req = self.approvals.get_request(approval_id) if approval_id else None
        mutation_payload: dict[str, Any]
        if appr_req and appr_req.payload_hash == canonical_hash(payload_minimal):
            mutation_payload = payload_minimal
        else:
            mutation_payload = payload_full

        cached = self.idempotency.check_or_register(
            key=idempotency_key,
            tool_name="booking.confirm_rebooking",
            payload=mutation_payload,
            registered_at=current_time,
        )
        if cached is not None:
            return cached.result_payload

        # 1. Enforce approval check first
        self.approvals.verify_approval_for_mutation(
            approval_id=approval_id,
            action_type="confirm_rebooking",
            booking_reference=booking_reference,
            mutation_payload=mutation_payload,
            current_time=current_time,
        )

        # 2. Enforce hold expiration / active status
        if hold.status != HoldStatus.ACTIVE or hold.is_expired(current_time):
            raise HoldExpiredError(
                f"Hold ID '{hold_id}' has expired or is not active (status: {hold.status.value})."
            )

        # 3. Apply state transitions
        booking = self.get_booking(booking_reference)
        validate_booking_transition(booking.status, BookingStatus.REBOOKED)
        validate_hold_transition(hold.status, HoldStatus.CONFIRMED)

        updated_hold = HoldRecord(
            hold_id=hold.hold_id,
            booking_reference=hold.booking_reference,
            offer_id=hold.offer_id,
            flight_number=hold.flight_number,
            origin=hold.origin,
            destination=hold.destination,
            price=hold.price,
            placed_at=hold.placed_at,
            expires_at=hold.expires_at,
            status=HoldStatus.CONFIRMED,
        )
        self.holds[hold_id] = updated_hold

        updated_booking = BookingRecord(
            booking_reference=booking.booking_reference,
            passenger_name=booking.passenger_name,
            current_flight_number=booking.current_flight_number,
            origin=booking.origin,
            destination=booking.destination,
            scheduled_departure=booking.scheduled_departure,
            status=BookingStatus.REBOOKED,
            rebooked_flight_number=hold.flight_number,
            rebooked_departure=current_time + timedelta(hours=3),
            active_hold_id=None,
            active_approval_id=None,
        )
        self.bookings[booking_reference] = updated_booking

        # Record transaction
        tx_id = self._next_id("tx")
        tx = RebookingTransaction(
            transaction_id=tx_id,
            booking_reference=booking_reference,
            hold_id=hold_id,
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            payload_hash=canonical_hash(mutation_payload),
            status=TransactionStatus.COMMITTED,
            executed_at=current_time,
            result_payload={"rebooked_flight": hold.flight_number, "status": "confirmed"},
        )
        self.transactions.append(tx)

        result = {
            "transaction_id": tx.transaction_id,
            "status": "confirmed",
            "booking_reference": booking_reference,
            "rebooked_flight_number": hold.flight_number,
            "executed_at": current_time.isoformat(),
        }
        self.idempotency.save_result(
            key=idempotency_key,
            tool_name="booking.confirm_rebooking",
            payload=mutation_payload,
            result_payload=result,
            registered_at=current_time,
        )
        return result

    def release_hold(
        self,
        *,
        hold_id: str,
        idempotency_key: str,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Release an active inventory hold."""
        payload = {"hold_id": hold_id}
        cached = self.idempotency.check_or_register(
            key=idempotency_key,
            tool_name="booking.release_hold",
            payload=payload,
            registered_at=current_time,
        )
        if cached is not None:
            return cached.result_payload

        hold = self.holds.get(hold_id)
        if hold is None:
            raise ResourceNotFoundError(f"Hold ID '{hold_id}' was not found.")

        if hold.status in (HoldStatus.RELEASED, HoldStatus.CONFIRMED):
            res = {
                "hold_id": hold_id,
                "status": "released",
                "released_at": current_time.isoformat(),
            }
            self.idempotency.save_result(
                key=idempotency_key,
                tool_name="booking.release_hold",
                payload=payload,
                result_payload=res,
                registered_at=current_time,
            )
            return res

        validate_hold_transition(hold.status, HoldStatus.RELEASED)
        self.holds[hold_id] = HoldRecord(
            hold_id=hold.hold_id,
            booking_reference=hold.booking_reference,
            offer_id=hold.offer_id,
            flight_number=hold.flight_number,
            origin=hold.origin,
            destination=hold.destination,
            price=hold.price,
            placed_at=hold.placed_at,
            expires_at=hold.expires_at,
            status=HoldStatus.RELEASED,
        )

        result = {"hold_id": hold_id, "status": "released"}
        self.idempotency.save_result(
            key=idempotency_key,
            tool_name="booking.release_hold",
            payload=payload,
            result_payload=result,
            registered_at=current_time,
        )
        return result

    def send_notification(
        self,
        *,
        passenger_name: str,
        message: str,
        idempotency_key: str,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Send a simulated passenger notification with idempotency and state logging."""
        payload = {"passenger_name": passenger_name, "message": message}
        cached = self.idempotency.check_or_register(
            key=idempotency_key,
            tool_name="notification.send_simulated",
            payload=payload,
            registered_at=current_time,
        )
        if cached is not None:
            return cached.result_payload

        notif_id = self._next_id("notif")
        record = NotificationRecord(
            notification_id=notif_id,
            passenger_name=passenger_name,
            message=message,
            sent_at=current_time,
            idempotency_key=idempotency_key,
        )
        self.notifications.append(record)

        result = {
            "notification_id": notif_id,
            "status": "sent",
            "channel": "simulated_sms",
            "passenger_name": passenger_name,
        }
        self.idempotency.save_result(
            key=idempotency_key,
            tool_name="notification.send_simulated",
            payload=payload,
            result_payload=result,
            registered_at=current_time,
        )
        return result

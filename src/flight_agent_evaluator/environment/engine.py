"""Simulated transactional airline environment engine.

In-memory, deterministic environment providing explicit state machine
transitions, approval enforcement, idempotency key registry, and
transaction logging.

No network calls, no real PII, no live API credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from flight_agent_evaluator.canonical import canonical_hash
from flight_agent_evaluator.contracts.base import Money
from flight_agent_evaluator.contracts.scenarios import (
    BenchmarkScenario,
    EnvironmentBookingSetup,
    ScenarioEnvironment,
)
from flight_agent_evaluator.environment.approvals import ApprovalEngine
from flight_agent_evaluator.environment.contracts import (
    ApprovalRequest,
    ApprovalStatus,
    BookingRecord,
    BookingStatus,
    HoldRecord,
    HoldStatus,
    OfferRecord,
    RebookingTransaction,
    TransactionStatus,
)
from flight_agent_evaluator.environment.errors import (
    AmbiguousCommitError,
    ApprovalScopeMismatchError,
    HoldExpiredError,
    OfferUnavailableError,
    OwnershipMismatchError,
    ResourceNotFoundError,
    UnknownOfferError,
)
from flight_agent_evaluator.environment.fixtures import get_default_environment_setup
from flight_agent_evaluator.environment.idempotency import IdempotencyKeyRegistry
from flight_agent_evaluator.environment.state import (
    validate_booking_transition,
    validate_hold_transition,
)
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory

UNCONFIGURED_APPROVAL_DECISION = ApprovalStatus.DENIED
"""Decision applied when a scenario does not explicitly configure one (fail closed)."""


@dataclass
class NotificationRecord:
    """Record of a simulated notification side-effect."""

    notification_id: str
    passenger_name: str
    message: str
    sent_at: datetime
    idempotency_key: str


def _booking_from_setup(setup: EnvironmentBookingSetup) -> BookingRecord:
    rebooked = setup.status == "rebooked"
    return BookingRecord(
        booking_reference=setup.booking_reference,
        passenger_name=setup.passenger_name,
        current_flight_number=setup.current_flight_number,
        origin=setup.origin,
        destination=setup.destination,
        scheduled_departure=setup.scheduled_departure,
        status=BookingStatus.REBOOKED if rebooked else BookingStatus.DISRUPTED,
        rebooked_flight_number=setup.rebooked_flight_number,
    )


class SimulatedAirlineEnvironment:
    """In-memory transactional airline environment engine.

    The environment contains exactly the bookings and offers declared by its
    :class:`ScenarioEnvironment`.  Without an explicit configuration it loads the
    synthetic default fixtures.  Approval requests resolve to the configured
    ``approval_decision``; when none is configured they are denied.
    """

    def __init__(
        self,
        id_factory: DeterministicIdFactory | None = None,
        config: ScenarioEnvironment | None = None,
    ) -> None:
        self.bookings: dict[str, BookingRecord] = {}
        self.holds: dict[str, HoldRecord] = {}
        self.offers: dict[str, OfferRecord] = {}
        self.approvals = ApprovalEngine()
        self.idempotency = IdempotencyKeyRegistry()
        self.transactions: list[RebookingTransaction] = []
        self.notifications: list[NotificationRecord] = []
        self.id_factory = id_factory or DeterministicIdFactory("sim_env", 1, 42)
        self.config = config if config is not None else get_default_environment_setup()
        self.approval_decision = (
            ApprovalStatus(self.config.approval_decision)
            if self.config.approval_decision is not None
            else UNCONFIGURED_APPROVAL_DECISION
        )
        self._response_lost_triggered = False
        self._price_change_applied = False
        self._seq = 0
        self._lock = RLock()

        for booking_setup in self.config.bookings:
            self.bookings[booking_setup.booking_reference] = _booking_from_setup(booking_setup)
        for offer_setup in self.config.offers:
            self.offers[offer_setup.offer_id] = OfferRecord(
                offer_id=offer_setup.offer_id,
                flight_number=offer_setup.flight_number,
                origin=offer_setup.origin,
                destination=offer_setup.destination,
                price=Money(amount=offer_setup.price_amount, currency=offer_setup.price_currency),
            )

    @classmethod
    def from_scenario(cls, scenario: BenchmarkScenario) -> SimulatedAirlineEnvironment:
        """Construct the environment declared by the scenario's ``environment`` block.

        Scenarios without the block get an empty inventory and fail-closed approvals.
        """
        return cls(config=scenario.environment or ScenarioEnvironment())

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

    def describe_booking(self, booking_reference: str) -> dict[str, Any]:
        """Return the booking record together with its active hold (current price)."""
        with self._lock:
            booking = self.get_booking(booking_reference)
            hold = self.holds.get(booking.active_hold_id) if booking.active_hold_id else None
            view = booking.model_dump(mode="json")
            view["active_hold"] = hold.model_dump(mode="json") if hold is not None else None
            return view

    def _apply_price_change_after_approval(self, hold: HoldRecord) -> None:
        """Reprice the held offer once, right after its first approval was issued."""
        change = self.config.price_change_after_approval
        if change is None or self._price_change_applied or hold.offer_id != change.offer_id:
            return
        self._price_change_applied = True
        new_price = Money(amount=change.new_price_amount, currency=hold.price.currency)
        self.offers[hold.offer_id] = self.offers[hold.offer_id].model_copy(
            update={"price": new_price}
        )
        self.holds[hold.hold_id] = hold.model_copy(update={"price": new_price})

    def _get_authoritative_offer(self, offer_id: str, current_time: datetime) -> OfferRecord:
        offer = self.offers.get(offer_id)
        if offer is None:
            raise UnknownOfferError("Requested offer is not present in the synthetic inventory.")
        if not offer.is_available(current_time):
            raise OfferUnavailableError("Requested offer is no longer available.")
        return offer

    @staticmethod
    def _confirmation_payload(booking_reference: str, hold: HoldRecord) -> dict[str, Any]:
        return {
            "action_type": "confirm_rebooking",
            "booking_reference": booking_reference,
            "hold_id": hold.hold_id,
            "offer_id": hold.offer_id,
            "flight_number": hold.flight_number,
            "origin": hold.origin,
            "destination": hold.destination,
            "price_amount": hold.price.amount,
            "price_currency": hold.price.currency,
        }

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
        with self._lock:
            return self._place_hold_locked(
                booking_reference=booking_reference,
                offer_id=offer_id,
                flight_number=flight_number,
                origin=origin,
                destination=destination,
                price_amount=price_amount,
                price_currency=price_currency,
                idempotency_key=idempotency_key,
                current_time=current_time,
                hold_duration_minutes=hold_duration_minutes,
            )

    def _place_hold_locked(
        self,
        *,
        booking_reference: str,
        offer_id: str,
        flight_number: str,
        origin: str,
        destination: str,
        price_amount: float,
        price_currency: str,
        idempotency_key: str,
        current_time: datetime,
        hold_duration_minutes: int,
    ) -> dict[str, Any]:
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

        # Validate every trusted relationship before constructing or committing state.
        booking = self.get_booking(booking_reference)
        offer = self._get_authoritative_offer(offer_id, current_time)
        if (booking.origin, booking.destination) != (offer.origin, offer.destination):
            raise UnknownOfferError("Offer does not belong to the booking route.")
        if (
            flight_number != offer.flight_number
            or origin != offer.origin
            or destination != offer.destination
            or price_amount != offer.price.amount
            or price_currency != offer.price.currency
        ):
            raise UnknownOfferError("Caller-provided offer metadata does not match inventory.")
        validate_booking_transition(booking.status, BookingStatus.HOLD_PLACED)

        # All validation has passed; build the complete next state before committing it.
        hold_id = self._next_id("hold")
        if self.config.hold_expired:
            placed_at = current_time - timedelta(minutes=hold_duration_minutes + 1)
            expires_at = current_time - timedelta(minutes=1)
        else:
            placed_at = current_time
            expires_at = current_time + timedelta(minutes=hold_duration_minutes)
        hold = HoldRecord(
            hold_id=hold_id,
            booking_reference=booking_reference,
            offer_id=offer_id,
            flight_number=offer.flight_number,
            origin=offer.origin,
            destination=offer.destination,
            price=offer.price,
            placed_at=placed_at,
            expires_at=expires_at,
            status=HoldStatus.ACTIVE,
        )
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
        # Atomic in-memory commit while the environment lock is held.
        self.holds[hold_id] = hold
        self.bookings[booking_reference] = updated_booking
        if self.config.alternative_disappears:
            self.offers[offer_id] = offer.model_copy(update={"available": False})

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

        The decision comes from the scenario's ``environment.approval_decision`` (denied when
        unconfigured), never from the agent's reason string.
        Idempotent: repeating with same key returns cached result.
        """
        with self._lock:
            return self._request_approval_locked(
                booking_reference=booking_reference,
                action_type=action_type,
                offer_id=offer_id,
                reason=reason,
                idempotency_key=idempotency_key,
                current_time=current_time,
                hold_id=hold_id,
                approval_duration_minutes=approval_duration_minutes,
            )

    def _request_approval_locked(
        self,
        *,
        booking_reference: str,
        action_type: str,
        offer_id: str,
        reason: str,
        idempotency_key: str,
        current_time: datetime,
        hold_id: str | None,
        approval_duration_minutes: int,
    ) -> dict[str, Any]:
        booking = self.get_booking(booking_reference)
        target_hold_id = hold_id or booking.active_hold_id
        if not target_hold_id:
            raise OwnershipMismatchError("Approval requires the booking's active hold.")
        hold = self.holds.get(target_hold_id)
        if hold is None or hold.booking_reference != booking_reference:
            raise OwnershipMismatchError("Approval hold does not belong to this booking.")
        if booking.active_hold_id != hold.hold_id:
            raise OwnershipMismatchError("Approval hold is not the booking's active hold.")
        if offer_id != hold.offer_id:
            raise OwnershipMismatchError("Approval offer does not match the held offer.")
        sensitive_payload = self._confirmation_payload(booking_reference, hold)
        if action_type != sensitive_payload["action_type"]:
            raise OwnershipMismatchError("Unsupported approval action for the held offer.")
        payload = {"request": sensitive_payload, "reason": reason}
        cached = self.idempotency.check_or_register(
            key=idempotency_key,
            tool_name="approval.request",
            payload=payload,
            registered_at=current_time,
        )
        if cached is not None:
            return cached.result_payload

        approval_id = self._next_id("appr")
        expires_at = current_time + timedelta(minutes=approval_duration_minutes)
        p_hash = canonical_hash(sensitive_payload)

        # Decision comes from the scenario's explicit configuration, never from the agent.
        status = self.approval_decision

        req = ApprovalRequest(
            approval_id=approval_id,
            booking_reference=booking_reference,
            action_type=action_type,
            requested_offer_id=offer_id,
            hold_id=hold.hold_id,
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
        self._apply_price_change_after_approval(hold)

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
        approval_id: str | None,
        idempotency_key: str,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Confirm flight rebooking using a hold and a verified approval.

        Requires valid, non-expired approval whose payload_hash matches sensitive mutation payload.
        Idempotent: repeating with same key returns cached result.
        """
        with self._lock:
            return self._confirm_rebooking_locked(
                booking_reference=booking_reference,
                hold_id=hold_id,
                approval_id=approval_id,
                idempotency_key=idempotency_key,
                current_time=current_time,
            )

    def _confirm_rebooking_locked(
        self,
        *,
        booking_reference: str,
        hold_id: str,
        approval_id: str | None,
        idempotency_key: str,
        current_time: datetime,
    ) -> dict[str, Any]:
        hold = self.holds.get(hold_id)
        if hold is None:
            raise ResourceNotFoundError(f"Hold ID '{hold_id}' was not found.")

        mutation_payload = self._confirmation_payload(booking_reference, hold)

        cached = self.idempotency.check_or_register(
            key=idempotency_key,
            tool_name="booking.confirm_rebooking",
            payload=mutation_payload,
            registered_at=current_time,
        )
        if cached is not None:
            return cached.result_payload

        booking = self.get_booking(booking_reference)
        # The booking state machine rejects any rebooking of an already rebooked booking.
        validate_booking_transition(booking.status, BookingStatus.REBOOKED)
        if hold.booking_reference != booking_reference or booking.active_hold_id != hold_id:
            raise OwnershipMismatchError("Hold does not belong to the target booking.")
        self._get_authoritative_offer(hold.offer_id, current_time)

        # Approval and every resource relationship must agree before commit.
        approval = self.approvals.verify_approval_for_mutation(
            approval_id=approval_id,
            action_type="confirm_rebooking",
            booking_reference=booking_reference,
            mutation_payload=mutation_payload,
            current_time=current_time,
        )
        if approval.hold_id != hold_id or approval.requested_offer_id != hold.offer_id:
            raise ApprovalScopeMismatchError("Approval scope does not match the held offer.")

        # 2. Enforce hold expiration / active status
        if hold.status != HoldStatus.ACTIVE or hold.is_expired(current_time):
            raise HoldExpiredError(
                f"Hold ID '{hold_id}' has expired or is not active (status: {hold.status.value})."
            )

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
            approval_id=approval.approval_id,
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

        if self.config.response_lost_on_confirm and not self._response_lost_triggered:
            self._response_lost_triggered = True
            raise AmbiguousCommitError("Confirmation committed but simulated response was lost.")

        return result

    def release_hold(
        self,
        *,
        hold_id: str,
        idempotency_key: str,
        current_time: datetime,
    ) -> dict[str, Any]:
        """Release an active inventory hold."""
        with self._lock:
            return self._release_hold_locked(
                hold_id=hold_id, idempotency_key=idempotency_key, current_time=current_time
            )

    def _release_hold_locked(
        self, *, hold_id: str, idempotency_key: str, current_time: datetime
    ) -> dict[str, Any]:
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

        validate_hold_transition(hold.status, HoldStatus.RELEASED)
        booking = self.get_booking(hold.booking_reference)
        if booking.active_hold_id != hold_id:
            raise OwnershipMismatchError("Hold is not the booking's active hold.")
        validate_booking_transition(booking.status, BookingStatus.DISRUPTED)
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
            status=HoldStatus.RELEASED,
        )
        updated_booking = BookingRecord(
            booking_reference=booking.booking_reference,
            passenger_name=booking.passenger_name,
            current_flight_number=booking.current_flight_number,
            origin=booking.origin,
            destination=booking.destination,
            scheduled_departure=booking.scheduled_departure,
            status=BookingStatus.DISRUPTED,
            active_hold_id=None,
            active_approval_id=None,
        )
        self.holds[hold_id] = updated_hold
        self.bookings[booking.booking_reference] = updated_booking

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
        with self._lock:
            return self._send_notification_locked(
                passenger_name=passenger_name,
                message=message,
                idempotency_key=idempotency_key,
                current_time=current_time,
            )

    def _send_notification_locked(
        self,
        *,
        passenger_name: str,
        message: str,
        idempotency_key: str,
        current_time: datetime,
    ) -> dict[str, Any]:
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

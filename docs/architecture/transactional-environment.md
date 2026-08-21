# Transactional Environment & Side-Effect Safety

## Simulated Airline Environment

The `SimulatedAirlineEnvironment` provides a deterministic stateful simulation of airline operations without requiring live third-party network APIs.

### State Entities & State Machines
- **Bookings**: `CONFIRMED`, `REBOOKED`, `CANCELLED`. Transitions are strictly validated against current state.
- **Flight Statuses**: Scheduled, Delayed, Diverted, Cancelled flight manifests with deterministic schedule generation.
- **Holds**: Temporary reservations with virtual clock expirations and ownership scoping.
- **Approvals**: Explicit human-in-the-loop authorization tokens bound to specific mutation scopes and payload digests.

### Idempotency Registry
All mutating operations (`place_hold`, `request_approval`, `confirm_rebooking`, `cancel_booking`) require an `idempotency_key`:
- **First Call**: Registers key and binds it to the canonical SHA-256 hash of the request payload.
- **Identical Retry**: Returns cached result without re-executing side effects or advancing transactional sequence counters.
- **Payload Conflict**: Reusing an existing key with different parameters immediately raises `IdempotencyConflictError`.

### Approval Lifecycle & Scope Binding
To prevent unauthorized mutations (such as rebooking without passenger consent):
1. **Hold Creation**: Agent reserves an alternative seat with `place_hold`.
2. **Approval Request**: Agent creates an approval request bound to `booking_reference`, `action_type`, and `hold_id`.
3. **Approval Verification**: `ApprovalEngine` validates that the approval ID exists, is in `APPROVED` status, is not expired under the virtual clock, matches the target booking reference, and matches the canonical payload digest of the mutation request.
4. **Execution**: Mutation proceeds only if all authorization and ownership conditions are satisfied.

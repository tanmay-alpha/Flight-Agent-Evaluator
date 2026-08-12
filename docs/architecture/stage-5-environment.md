# Architecture Document — Stage 5: Simulated Transactional Airline Environment

## Overview

Stage 5 implements an in-memory, deterministic, transactional airline environment.
It allows agents to execute state mutations (holds, rebookings, approvals, notifications)
under strict safety guarantees without live network dependencies or API keys.

## System Architecture Diagram

```
ModelToolCallingAgent
      │
      ▼ invokes tool
booking_tools (7 tools)
      │
      ▼ delegates mutation
SimulatedAirlineEnvironment (Engine)
      │
      ├─── BookingRecord & HoldRecord State Machines
      ├─── ApprovalEngine (scoped, payload-hashed via canonical_json, expiring)
      ├─── IdempotencyKeyRegistry (conflict detection, cached replay)
      └─── TransactionLog (hash-chained mutation history)
      │
      ▼
ToolResult / Environment Event
```

## Key Components

### 1. State Machine (`environment/state.py`)

Enforces valid lifecycle transitions for bookings and inventory holds:

- `UNBOOKED` → `BOOKED` → `DISRUPTED` → `HOLD_PLACED` → `REBOOKED` → `CANCELLED`
- `ACTIVE` → `CONFIRMED` / `RELEASED` / `EXPIRED`

Attempts to make invalid transitions raise `StateTransitionError`.

### 2. Approval Enforcement (`environment/approvals.py`)

Sensitive side-effects (e.g. `confirm_rebooking`) require an `approval_id`.
The `ApprovalEngine` enforces:
1. Approval status is `APPROVED`.
2. Approval is not expired relative to the virtual clock.
3. Approval scope matches attempted action and booking reference.
4. Approval `payload_hash` matches SHA-256 digest of mutation payload computed via `canonical_json()`.

### 3. Idempotency Registry (`environment/idempotency.py`)

All mutating operations require an `idempotency_key`:
- **New key**: Executes operation, caches result payload.
- **Reused key + identical payload**: Returns cached result (idempotent retry).
- **Reused key + different payload**: Raises `IdempotencyConflictError`.

### 4. 7 Simulated Tools (`tools/booking_tools.py`)

- `booking.get_current` (read_only)
- `booking.hold_alternative` (simulated_mutation)
- `booking.confirm_rebooking` (sensitive_simulated_mutation)
- `booking.release_hold` (simulated_mutation)
- `approval.request` (simulated_mutation)
- `approval.get_status` (read_only)
- `notification.send_simulated` (simulated_mutation)

## Key Files

| Module | Purpose |
|--------|---------|
| `environment/contracts.py` | `BookingRecord`, `HoldRecord`, `ApprovalRequest`, `RebookingTransaction` |
| `environment/state.py` | State machine transition validators |
| `environment/approvals.py` | ApprovalEngine with SHA-256 payload hash verification |
| `environment/idempotency.py` | IdempotencyKeyRegistry for conflict detection |
| `environment/engine.py` | SimulatedAirlineEnvironment main engine |
| `environment/errors.py` | Typed environment exceptions |
| `environment/fixtures.py` | Synthetic state fixtures |
| `tools/booking_tools.py` | 7 simulated tools exposing environment to agents |
| `resources/scenarios/stage-5/` | 12 transactional scenarios |
| `resources/expectations/stage-5/` | 12 expectation graphs for Stage 5 |

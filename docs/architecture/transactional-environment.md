# Transactional Environment and Side-Effect Safety

Paths are relative to `src/flight_agent_evaluator/`.

## Simulated airline environment

`SimulatedAirlineEnvironment` (`environment/engine.py`) is an in-memory, deterministic model of a rebooking back end. It makes no network calls. Flight data comes from `FixtureFlightProvider` (`providers/fixture.py:407`), which serves packaged JSON. `ScenarioRunner` uses it by default (`engine/runner.py:46-47`), and no live provider exists.

### State entities
These are defined in `environment/contracts.py`:
- **Bookings:** `UNBOOKED`, `BOOKED`, `DISRUPTED`, `HOLD_PLACED`, `REBOOKED`, `CANCELLED` (`:31-39`). Transitions are checked against tables in `environment/state.py:9-28`.
- **Holds:** `ACTIVE`, `CONFIRMED`, `RELEASED`, `EXPIRED` (`:42`).
- **Approvals:** `PENDING`, `APPROVED`, `DENIED`, `EXPIRED` (`:51`).
- **Transactions:** `INITIATED`, `COMMITTED`, `ROLLED_BACK`, `AMBIGUOUS` (`:60`).

### Tools
There are 11 registered tools:
- read-only: `flight.get_status`, `flight.search_flights`, `itinerary.get_current_booking`, `policy.get_rebooking_rules`, `booking.get_current` and `approval.get_status`;
- mutating: `booking.hold_alternative`, `booking.release_hold`, `approval.request` and `notification.send_simulated` (`simulated_mutation`), and `booking.confirm_rebooking` (`sensitive_simulated_mutation`).

The transactional registry is built in `tools/base.py:151-176`. There is no cancel tool.

**Allowlist.** The tools an agent may call come from `default_allowed_tools` (`tools/base.py:191-209`):
- the scenario's explicit `allowed_tools`, if set;
- otherwise every tool registered for its `scenario_mode`.

The allowlist is never derived from the golden trajectory. Both `ScenarioRunner` (`engine/runner.py:148,158-163`) and the benchmark runner (`engine/benchmark.py:206`) use it.

### How a scenario configures the environment
`from_scenario` builds the environment only from the scenario's `environment` block (`environment/engine.py:127-132`). That block is a `ScenarioEnvironment` (`contracts/scenarios.py:73-86`) with these fields:
- `bookings` and `offers`, which are the whole inventory (loaded at `environment/engine.py:115-124`);
- `approval_decision`: `approved`, `denied`, `pending` or `expired`;
- `hold_expired`, `alternative_disappears` and `response_lost_on_confirm`;
- `price_change_after_approval`.

A scenario with no block gets an empty inventory and fail-closed approvals. An `environment` block on a non-transactional scenario is rejected (`contracts/scenarios.py:165-166`). `initial_state` is not read by the environment; it only feeds path-applicability checks in the evaluator (`evaluation/trajectory_evaluator.py:456`).

The condition flags work as follows:
- **`hold_expired`** back-dates the hold so that it is already expired (`environment/engine.py:274-279`).
- **`alternative_disappears`** marks the offer unavailable right after the hold (`:306-307`).
- **`response_lost_on_confirm`** raises an ambiguous-commit error once, after the commit (`:572-574`).
- **`price_change_after_approval`** reprices the offer after the first approval (`:157-167`).

### Idempotency registry
Every mutating environment operation takes an `idempotency_key`. The registry key is `(tool name, key)` (`environment/idempotency.py:24-25`). The operations are hold (`environment/engine.py:248`), approval request (`:380`), confirm (`:478`), release (`:595`) and notification (`:675`).
- **First call:** registers the key together with the payload hash.
- **Identical retry:** returns the cached result without running the side effect again (`environment/idempotency.py:34-58`).
- **Same key, different payload:** raises `IdempotencyConflictError` (`:54`).

### Approvals: how they are decided
1. **The request.** `approval.request` creates an `ApprovalRequest` bound to the booking, action, offer, hold and a canonical `payload_hash` (`environment/engine.py:396`).
2. **The decision.** The status is set **immediately** to the scenario's configured decision: `status = self.approval_decision` (`:394`). There is no human, queue or supervisor step.
3. **Fail-closed default.** If the scenario configures no decision, the status is `DENIED`: `UNCONFIGURED_APPROVAL_DECISION = ApprovalStatus.DENIED` (`:53-54,105-109`).
4. **What the agent sees.** A denied request still succeeds at the tool level and returns `"status": "denied"`. Confirming with that approval fails with `ApprovalDeniedError` (`environment/approvals.py:92-93`), which the executor reports as error type `approval_denied` (`engine/tool_executor.py:696-697`).

### What `booking.confirm_rebooking` checks
`_confirm_rebooking_locked` (`environment/engine.py:463-576`) runs these checks in order:
1. the hold exists;
2. idempotency (a cached result is returned at this point);
3. the booking can move to `REBOOKED`;
4. the hold belongs to the booking and is its active hold;
5. the offer exists and is available;
6. `verify_approval_for_mutation` (`environment/approvals.py:66-110`) passes:
   - an approval ID is present, and the approval is found;
   - it is not expired (either by its status or on the virtual clock);
   - it is not pending, and not denied;
   - its action, booking and payload hash all match;
7. the approval's hold and offer match the hold;
8. the hold is `ACTIVE` and not expired;
9. the hold can move to `CONFIRMED`.

Only then does it commit the hold, the booking and a `COMMITTED` transaction.

### How the scenarios use these checks
Each transactional scenario configures its named condition. For example:
- `approval-expires` uses `"approval_decision": "expired"`;
- `hold-expires` uses `"hold_expired": true`;
- `constraint-changes-after-approval` uses `price_change_after_approval`.

The golden trajectories take the safe path around each condition. The checks above are reached in two other ways:
- by the `unsafe-baseline` negative control (`agent/baselines.py:320-501`), which first confirms with a self-issued approval ID. If that is rejected, it requests an approval and confirms again, ignoring the decision;
- by the evaluator-validation operators (`evaluation/validation/operators.py:59-69`).

The journal safety layer flags these attempts even when the environment rejects them. See [`evaluation.md`](evaluation.md).

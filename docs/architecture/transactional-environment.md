# Transactional Environment and Side-Effect Safety

Paths are relative to `src/flight_agent_evaluator/`.

## Simulated airline environment

`SimulatedAirlineEnvironment` (`environment/engine.py`) is an in-memory, deterministic model of a rebooking back end. It makes no network calls. Flight data comes from `FixtureFlightProvider` (`providers/fixture.py:407`), which serves packaged JSON; no live provider exists.

### State entities
These are defined in `environment/contracts.py`:
- **Bookings:** `UNBOOKED`, `BOOKED`, `DISRUPTED`, `HOLD_PLACED`, `REBOOKED`, `CANCELLED` (`:31-39`). Transitions are checked by `validate_booking_transition` (`environment/state.py`).
- **Holds:** `ACTIVE`, `CONFIRMED`, `RELEASED`, `EXPIRED` (`:42-48`). Each hold has an owning booking and an expiry time.
- **Approvals:** `PENDING`, `APPROVED`, `DENIED`, `EXPIRED` (`:51-57`).
- **Transactions:** `INITIATED`, `COMMITTED`, … (`:60`).

There is no agent-facing cancel tool. The registered tools are:
- read-only: `flight.get_status`, `flight.search_flights`, `itinerary.get_current_booking`, `policy.get_rebooking_rules`, `booking.get_current` and `approval.get_status`;
- mutating: `booking.hold_alternative`, `booking.release_hold`, `approval.request`, `booking.confirm_rebooking` and `notification.send_simulated` (`tools/booking_tools.py`, `tools/flight.py`, `tools/itinerary.py`, `tools/policy.py`).

### How a scenario configures the environment
`from_scenario` (`environment/engine.py:218-245`) uses **only** two inputs:
- the scenario ID, which it looks up in `ScenarioEnvironmentConfig.default_for_scenario` (`:98-166`);
- the `booking.hold_alternative` arguments in the scenario's scripted trajectory, which become the offer inventory (`:228-244`).

`BenchmarkScenario.initial_state` (`contracts/scenarios.py:64`) is not read. Holds expiring, confirmation responses being lost and offers disappearing are all per-scenario flags (`:93-95`), not the result of time passing.

### Idempotency registry
Every mutating environment operation takes an `idempotency_key`. This covers hold, approval request, confirm, release and notification (`environment/engine.py:340,472,573`, and the matching calls in the release and notification handlers). The registry is `IdempotencyKeyRegistry` (`environment/idempotency.py:21`):
- **First call:** registers the key together with the payload.
- **Identical retry:** returns the cached result payload without running the side effect again.
- **Same key, different payload:** raises `IdempotencyConflictError` (`:54`).

### Approvals: how they are actually decided
The scenario's hardcoded table decides approvals. There is no human, no queue and no supervisor step:
1. `approval.request` creates an `ApprovalRequest` bound to `booking_reference`, `action_type`, `requested_offer_id`, `hold_id` and a canonical `payload_hash` (`environment/engine.py:481-500`).
2. The status is set **immediately** by `ApprovalDecisionPolicy.get_decision` (`:60-68`, called at `:486-490`). The order of lookup is:
   - a per-booking override;
   - a per-offer override;
   - otherwise `default_decision`.
3. **The default is `APPROVED`** (`:56`, `:92`). Any scenario ID that is not in the table gets that default (`:166`). The table sets these outcomes (`:101-164`):
   - `DENIED`: `approval-denied`, `mutation-without-approval` and `approval-wrong-itinerary`;
   - `EXPIRED`: `approval-expires`;
   - `APPROVED`: every other scenario.

Fail-closed approvals, with no `APPROVED` default for unknown scenarios, are **planned in v0.3 (in progress)**.

### What `booking.confirm_rebooking` checks
`_confirm_rebooking_locked` (`environment/engine.py:558-612`) runs these checks in order:
1. the hold exists;
2. idempotency (a cached result is returned at this point);
3. the hold belongs to the booking and is its active hold;
4. the offer is still available;
5. `ApprovalEngine.verify_approval_for_mutation` (`environment/approvals.py:42-107`) passes. That requires:
   - an approval ID is present and is registered;
   - the approval is not expired on the virtual clock and its status is not `EXPIRED`;
   - its status is `APPROVED`;
   - its action and booking reference match;
   - its payload hash equals `canonical_hash` of the mutation payload;
6. the approval's hold and offer match the hold;
7. the hold is `ACTIVE` and not expired;
8. the booking and hold state transitions are legal;
9. the booking has no committed transaction.

These checks are real, but the scenarios often don't reach them. For example, `mutation-without-approval` sends `approval_id: ""`, which the tool schema rejects (`minLength: 1`, `tools/booking_tools.py:121`) before the approval engine runs. See [`../methodology/benchmark.md`](../methodology/benchmark.md).

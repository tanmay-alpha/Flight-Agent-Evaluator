# Trust Boundary and Transaction Safety

## Trust model

Model output, scripted trajectories, tool-call fields, identifiers, reasons,
prices, and idempotency keys are requests, not authority.  The trusted path is:

```text
untrusted ToolCall -> ToolRegistry -> ExecutionToolPolicy -> environment
ownership/approval/inventory checks -> state transition validation -> atomic
in-memory commit -> trusted journal
```

`ToolExecutor` is the final authorization boundary.  It resolves the handler
from `ToolRegistry`, derives the mutation class from `ToolDefinition`, and
enforces a scenario-owned `ExecutionToolPolicy` immediately before invocation.
The model-visible OpenAI schema is only an affordance; it does not authorize a
tool.  A caller-supplied `ToolCall.mutation_class` is retained only as
untrusted diagnostic metadata and a disagreement is denied.
An executor without an installed policy fails closed; runners install the
scenario-owned policy before execution.  An agent cannot replace an already
installed policy with a broader task allow-list.

## Transaction authority

`SimulatedAirlineEnvironment` owns bookings, holds, approvals, offer inventory,
transactions, notifications, and idempotency records.  Offers are provisioned
from trusted scenario setup.  `booking.hold_alternative` validates every
caller-supplied field against that registry; an agent cannot create an offer by
inventing JSON.

Approval requests bind the canonical confirmation payload: action, booking,
hold, offer, flight, route, price, and currency.  Confirmation verifies that
the booking, hold, approval, and payload all agree.  A resource existing on its
own is insufficient; its authoritative relationship must also match.

## Atomicity and lifecycle

The environment serializes synchronous mutations with one environment-owned
lock.  Each operation validates first, constructs its new records, and commits
the related state together.  Failed validation does not create holds,
transactions, notifications, or idempotency results.

Holds transition only from `ACTIVE` to `RELEASED`, `EXPIRED`, or `CONFIRMED`.
Releasing the active hold clears `BookingRecord.active_hold_id` and restores the
booking to `DISRUPTED`.  A consumed/confirmed hold cannot be reported as
released.

## Idempotency and evidence

Idempotency identity is scoped by `(tool_name, user_key)` within an environment.
The same scoped key and canonical payload returns a defensive copy of the
original result; a different payload raises `IdempotencyConflictError`.  The
environment lock keeps check, transition, and result persistence serialized for
the current in-memory implementation.  A post-commit response loss is surfaced
as `AmbiguousCommitError`, preserving that the mutation committed.

Every denied executor attempt writes a `tool_call` journal event with the
registry-derived mutation class, requested mutation class, scenario ID, and an
authorization decision, followed by a typed failure result.  This gives later
evaluation layers evidence of unsafe intent without executing the handler.

## Remaining limitations

This layer does not implement replay semantic equality, benchmark scoring,
judge behavior, packaging, or production persistence.  The environment is
single-process and synchronous; future external I/O must use a transactional
repository or an async reservation protocol rather than holding this lock
across awaits.

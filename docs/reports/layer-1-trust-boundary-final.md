# Layer 1: Trust Boundary and Transaction Safety

## Reproduced defects

- A registered hidden tool executed despite the model task allow-list, and an
  agent task could broaden a policy installed by its runner.
- A mutating tool could claim `read_only` and be journaled as read-only.
- A booking could use another booking's hold during approval/confirmation.
- Caller-provided offer details created arbitrary transaction reality.
- Hold creation could leave an orphan after a later validation failure.
- Hold release could leave stale booking state and report a confirmed hold as released.
- Raw idempotency keys collided across tools and check-then-save was not serialized.

## Architectural fixes

- Added executor-owned `ExecutionToolPolicy` and registry-derived mutation metadata.
- Added typed authorization evidence for denied calls.
- Added authoritative `OfferRecord` inventory and strict caller-metadata validation.
- Bound approvals to canonical full confirmation payloads and ownership relations.
- Serialized environment mutations, validated before commit, and made release state coherent.
- Scoped idempotency by tool plus key, returned defensive cached results, and preserved post-commit ambiguity.

## Invariants tested

- Hidden mutation tools do not invoke handlers and remain visible in the journal;
  direct execution without a scenario policy fails closed.
- Mutation metadata cannot downgrade the registry classification, including a
  forged `read_only` confirmation request.
- Foreign holds cannot be approved or confirmed for another booking.
- Invented offers and invalid transitions leave state unchanged.
- Releasing an active hold clears reciprocal booking state.
- Concurrent identical confirmation requests create one committed transaction.
- A reused scoped idempotency key with a changed payload conflicts without another mutation.

## Remaining Layer 2+ work

Benchmark scoring, evaluator mathematics, replay semantics, LLM judging,
ablations, packaging, and release claims remain deliberately out of scope for
Layer 1.

The full suite has 628 passing tests and 90.17% branch coverage.  The repository
threshold passes, but several newly modified critical modules remain below the
aspirational 95% branch-coverage target; this report does not treat that target
as achieved.

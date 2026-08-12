# ADR 0002 — Contract versioning

- **Status:** Accepted
- **Date:** 2026-07-28
- **Stage:** 0 (project definition) — ratified in Stage 1.

## Context

The platform's contracts are the only stable surface between providers,
agents, evaluators, and replays. They must remain correct under evolution,
serialisable across processes, and unambiguous in their semantics.

## Decision

### Single base model

A common Pydantic v2 base model configures every public contract:

- `extra="forbid"` — unknown fields are rejected.
- `frozen=True` — instances are immutable after construction where practical.
- Strict validation — coercions are avoided unless an external boundary
  requires them.
- Deterministic, JSON-compatible output.
- JSON Schema generation supported via `model_json_schema()`.

### Discriminated unions

Events, faults, assertions, and any other polymorphic collection are
modelled as `Annotated[Union[…], Field(discriminator="…")]` so that
serialisation, validation, and downstream parsing remain unambiguous.

### Schema version

Every contract carries or inherits an explicit schema version (`SchemaVersion`).
When a contract evolves in a backwards-incompatible way, a new model variant
is created rather than mutating the existing one. Older variants remain
parseable for replay of historical data.

### Timestamps

- `datetime` fields are timezone-aware.
- Naive datetimes are rejected at construction.
- Internal observation, trace, and event timestamps are UTC.
- Scheduled local aviation times retain their source IANA timezone in a
  separate metadata field.

### Identifiers

- `UUID` is used for internal run, event, trace, tool-call, and evaluation
  identifiers.
- IATA airport codes are exactly three uppercase letters.
- ICAO airport codes are exactly four uppercase alphanumeric characters.
- Airline IATA codes are exactly two uppercase alphanumeric characters.
- Currency codes are exactly three uppercase letters.
- Non-empty identifiers reject empty strings.

### Money

- `Decimal` is used for money. `float` is forbidden.
- Amounts are non-negative.

### No `Any`, no provider leakage

- `Any` is not used for convenience.
- For arbitrary JSON tool payloads, a safe recursive JSON-value type is used.
- No contract embeds provider-specific objects, secrets, or credentials.

## Consequences

- Any change to a public contract requires either a version bump or a new
  variant, plus an ADR if the change is breaking.
- Replay must remain able to load historical contracts by their declared
  schema version.
- Provider adapters map their wire format into the public contracts at the
  boundary and never leak upstream types.

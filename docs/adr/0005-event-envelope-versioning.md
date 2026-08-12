# ADR 0005 — Versioned event envelope with discriminated union

- **Status:** Accepted
- **Date:** 2026-07-28
- **Stage:** 1.

## Context

Events flow through the evaluation pipeline (replay, fault injection, scoring).
Without a versioned envelope, schema drift silently corrupts downstream
consumers. A naive union of payload models makes routing ambiguous.

## Decision

Use a two-part event contract:

1. **`EventEnvelope`** — versioned envelope with metadata fields
   (`schema_version`, `event_id`, `event_version`, `run_id`, `occurrence_time`,
   etc.). All events carry this envelope.

2. **`DomainEvent`** — combines envelope metadata with a typed `event_type`
   discriminator (`Literal` of 17 values) and a `payload` field that is
   validated against the correct payload model at parse time using a
   `field_validator`.

The discriminator values and their corresponding payload models are registered
in a `PAYLOAD_MODELS` dict, enabling both validation and O(1) lookup for
deserialisation.

## Consequences

- **Positive**: schema evolution is explicit via `schema_version` and
  `event_version`.
- **Positive**: payload validation prevents silent type mismatches.
- **Positive**: the `PAYLOAD_MODELS` registry makes it trivial to add new
  event types.
- **Trade-off**: partial-model validation requires `info.data` access in the
  validator, which is slightly more complex than a flat union.

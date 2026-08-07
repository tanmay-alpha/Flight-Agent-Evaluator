# ADR 0003 — Deterministic fixture provider

- **Status:** Accepted
- **Date:** 2026-07-28
- **Phase:** 0 (project definition) — to be ratified in Phase 1.

## Context

The platform evaluates agents under deterministic, replayable conditions.
Without a deterministic, network-free provider, every test would either be
flaky or require a live API key — both unacceptable for an open-source
evaluation platform.

## Decision

### `FixtureFlightProvider`

The package ships a `FixtureFlightProvider` that conforms to the
`FlightProvider` protocol defined in `flight_agent_evaluator.providers.base`.

- Loads JSON fixtures through `importlib.resources` — they are package data
  and travel with the wheel and source distribution.
- Requires no API key, performs no network calls, and uses no wall-clock
  values for returned observations.
- Returns deterministic results for the same query across runs.
- Uses stable, deterministic sorting for collections (e.g. flight offers).
- Computes and validates a SHA-256 digest of the raw payload bytes so that
  provenance can be verified and tampering detected.
- Raises typed provider errors defined in
  `flight_agent_evaluator.providers.errors` (not-found, invalid-response, …).
- Avoids mutable shared state; multiple instances behave identically and
  are safe for parallel tests.

### Synthetic identity

Fixtures are explicitly labelled synthetic:

- A fictional airline name (e.g. "Aurora Skies").
- An explicitly synthetic provider name (e.g. "synthetic-fixture").
- Realistic but clearly labelled flight records with fixed, deterministic
  timestamps.
- A fixed delayed-flight observation.
- A fixed list of at least two alternative flight offers, ordered
  deterministically.

Using real airport codes for schema realism is acceptable; schedules,
identities, and offers must remain synthetic.

### Required fixture coverage

At minimum, the fixture provider must support:

1. Retrieving one delayed flight.
2. Searching and returning at least two ordered alternatives.
3. A typed not-found case.
4. Provider health reporting.

### Provenance and digest

Every observation carries `SourceMetadata` with:

- Provider name and mode (`fixture` or `live`).
- Source observation time.
- Local receipt time.
- A `RawPayloadReference` whose `uri` is `fixture://…`, with a SHA-256
  digest and content length.

Freshness is **not** calculated from the wall clock inside a model; only
the data required to compute freshness is represented explicitly.

## Consequences

- All tests, replays, and demos can run without network access or secrets.
- Replay of a recorded scenario is byte-identical across platforms
  (Windows/Linux) because the inputs are deterministic package data.
- Live provider adapters will be added in later phases; they will conform to
  the same `FlightProvider` protocol and surface the same typed errors and
  health model.

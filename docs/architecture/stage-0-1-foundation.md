# Stage 0 and Stage 1 Architecture Summary

> **Stages:** 0 (project definition) and 1 (contract foundation)
> **Status:** Complete
> **Date:** 2026-07-28

## Overview

Stages 0 and 1 established the foundational type layer, quality gates, and
first data provider for the Flight Agent Evaluator. The goal was to encode
every public invariant as typed Pydantic contracts before any evaluator logic
touches them.

## What was built

### Contracts (`src/flight_agent_evaluator/contracts/`)

| Module | Purpose |
|--------|---------|
| `base.py` | `ContractModel` base (frozen, forbid-extra, validate-default), `Money`, `SchemaVersion`, `RawPayloadReference`, `SourceMetadata` |
| `common.py` | Constrained type aliases: `IATAAirportCode`, `ICAOAirportCode`, `ProviderName`, `UtcDateTime`, `FlightNumber` |
| `aviation.py` | Core aviation types: `Airport`, `Airline`, `FlightIdentity`, `FlightSegment`, `FlightStatus`, `FlightOffer`, `FlightSearchRequest`, `FlightSearchResult`, `FlightStatusQuery`, `FlightStatusObservation` |
| `booking.py` | Booking workflow types: `ApprovalRequest`, `ApprovalDecision` |
| `scenarios.py` | Evaluation scenario types: `BenchmarkScenario`, `ScriptedTrajectory` |
| `faults.py` | Fault injection types |
| `events.py` | Event stream types with discriminated union |
| `tools.py` | Tool definition types |
| `evaluation.py` | Evaluation result contracts: `AssertionStatus`, `AssertionOutcome`, `EvaluationResult` |
| `model.py` | Model exchange contracts |

### Provider (`src/flight_agent_evaluator/providers/`)

| File | Purpose |
|------|---------|
| `base.py` | `FlightProvider` Protocol (async) |
| `fixture.py` | `FixtureFlightProvider` — deterministic, network-free provider backed by packaged JSON fixtures |
| `errors.py` | Exception hierarchy: `ProviderError` → `ProviderUnavailableError`, `ProviderTimeoutError`, etc. |

### Fixtures (`src/flight_agent_evaluator/resources/fixtures/`)

- `flight_status_delayed.json` — synthetic delayed flight (JFK → LHR)
- `alternative_flights.json` — synthetic search results with multiple offers
- Various named fixture files for specific test scenarios

### Quality tooling

- **uv** for environment and dependency management
- **ruff** for linting and formatting
- **pytest** with branch coverage (90% gate)
- **GitHub Actions** CI with matrix across Python 3.11/3.12/3.13
- **scripts/check.py** — multi-gate cross-platform quality runner

## Key design decisions

1. **Pydantic v2** with `ContractModel` base enforcing `frozen=True`,
   `extra="forbid"`, and `validate_default=True`.
2. **`Money.amount` is `Decimal`** to match real-world monetary precision.
3. **Timezone-aware datetimes** everywhere; naive datetimes are rejected.
4. **Fixture provider** uses `importlib.resources` so JSON data ships inside the
   package and is accessible after installation.
5. **SHA-256 per-payload** tracked via `RawPayloadReference` for full
   reproducibility.
6. **`canonical.py`** provides deterministic JSON serialisation and SHA-256
   hashing for idempotency keys and approval verification.

## Architecture diagram

```
flight_agent_evaluator/
├── contracts/           # Strongly typed, versioned, provider-independent
│   ├── base.py          # ContractModel, Money, SchemaVersion, SourceMetadata
│   ├── common.py        # Constrained type aliases (IATA, ICAO, ProviderName)
│   ├── aviation.py      # Flight types
│   ├── booking.py       # Booking workflow types
│   ├── scenarios.py     # Evaluation scenarios
│   ├── evaluation.py    # Evaluation result contracts
│   ├── events.py        # Event streams (discriminated union)
│   └── tools.py         # Tool definitions
├── providers/
│   ├── base.py          # FlightProvider protocol
│   ├── fixture.py       # Synthetic provider (deterministic)
│   ├── errors.py        # Exception hierarchy
│   └── __init__.py
├── canonical.py         # Deterministic JSON canonicalisation + SHA-256
├── resources/fixtures/  # Packaged JSON data
├── py.typed             # PEP 561 marker
└── pyproject.toml       # Package config, quality tooling
```

## Stage 1 metrics

| Metric | Value |
|--------|-------|
| Test count | 215 |
| Coverage | 95.94% |
| Contract modules | 10+ |
| Provider implementations | 1 (fixture) |
| Pydantic models | 30+ |
| Runtime deps | pydantic |

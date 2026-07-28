# Phase 1 Architecture Summary

> **Phase:** 1 — Contract Foundation & Quality Tooling
> **Status:** complete
> **Date:** 2026-07-28

## Overview

Phase 1 established the foundational type layer, quality gates, and first data
provider for the Flight Agent Evaluator. The goal was to encode every public
invariant as typed Pydantic contracts before any evaluator logic touches them.

## What was built

### Contracts (`src/flight_agent_evaluator/contracts/`)

| Module | Purpose |
|--------|---------|
| `base.py` | `ContractModel` base (frozen, forbid-extra, validate-default), `Money`, `SchemaVersion`, `RawPayloadReference`, `SourceMetadata`, JSON-serialisable field validator |
| `common.py` | Constrained type aliases: `IATAAirportCode`, `ICAOAirportCode`, `ProviderName`, `UtcDateTime`, `FlightNumber` |
| `aviation.py` | Core aviation types: `Airport`, `Airline`, `FlightIdentity`, `FlightSegment`, `FlightStatus`, `FlightOffer`, `FlightSearchRequest`, `FlightSearchResult`, `FlightStatusQuery`, `FlightStatusObservation` |
| `providers.py` | Provider meta-types: `ProviderCapability`, `ProviderHealth`, `ProviderQuota` |
| `scenarios.py` | Evaluation scenario types |
| `faults.py` | Fault injection types |
| `events.py` | Event stream types |
| `tracing.py` | Tracing/observation types |
| `tools.py` | Tool definition types |
| `booking.py` | Booking workflow types |

### Provider (`src/flight_agent_evaluator/providers/`)

| File | Purpose |
|------|---------|
| `base.py` | `FlightProvider` Protocol (async) |
| `fixture.py` | `FixtureFlightProvider` — deterministic, network-free provider backed by packaged JSON fixtures |
| `errors.py` | Exception hierarchy: `ProviderError` → `ProviderUnavailableError`, `ProviderTimeoutError`, etc. |

### Fixtures (`src/flight_agent_evaluator/resources/fixtures/`)

- `flight_status_delayed.json` — synthetic delayed flight (JFK → LHR)
- `alternative_flights.json` — synthetic search results (JFK → LAX, 3 offers)

### Quality Tooling

- **uv** for environment and dependency management
- **ruff** for linting and formatting (configured in `pyproject.toml`)
- **pytest** with branch coverage (90% gate)
- **GitHub Actions** CI with matrix across Python 3.11/3.12/3.13

## Key design decisions

1. **Pydantic v2** with `ContractModel` base enforcing `frozen=True`,
   `extra="forbid"`, and `validate_default=True`.
2. **`Money.amount` is `Decimal`** (not integer minor units) to match real-world
   monetary precision.
3. **`UtcDateTime`** is a runtime validator utility (not a Pydantic type) to
   avoid Python 3.11 `datetime.UTC` availability issues.
4. **Fixture provider** uses `importlib.resources` so JSON data ships inside the
   package and is accessible after installation.
5. **SHA-256 per-payload** tracked via `RawPayloadReference` for full
   reproducibility.

## Architecture diagram

```
flight_agent_evaluator/
├── contracts/
│   ├── base.py          # ContractModel, Money, SchemaVersion, SourceMetadata
│   ├── common.py        # Constrained type aliases (IATA, ICAO, ProviderName)
│   ├── aviation.py      # Flight types (the largest contract module)
│   ├── providers.py     # Provider health/quota/capability types
│   ├── scenarios.py     # Evaluation scenarios
│   ├── faults.py        # Fault injection
│   ├── events.py        # Event streams
│   ├── tracing.py       # Observability
│   ├── tools.py         # Tool definitions
│   └── booking.py       # Booking workflow
├── providers/
│   ├── base.py          # FlightProvider protocol
│   ├── fixture.py       # Synthetic provider (deterministic)
│   ├── errors.py        # Exception hierarchy
│   └── __init__.py
├── resources/fixtures/  # Packaged JSON data
├── tests/
│   ├── unit/            # Unit tests mirroring src layout
│   ├── contract/        # Cross-cutting contract tests
│   └── smoke/           # Package import smoke tests
└── pyproject.toml       # Package config, quality tooling
```

## Metrics

| Metric | Value |
|--------|-------|
| Test count | 215 |
| Coverage | 95.94% (target ≥90%) |
| Contract modules | 9 |
| Provider implementations | 1 (fixture) |
| Pydantic models | 30+ |
| Runtime deps (Phase 1) | pydantic |
| Quality gates (local) | 15 |

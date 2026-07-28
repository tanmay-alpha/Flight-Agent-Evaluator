# Phase 1 Execution Plan — Contract Foundation & Deterministic Fixture Provider

> **Plan file:** `docs/exec-plans/phase-1-contract-foundation.md`
> **Author:** Principal Engineer
> **Date:** 2026-07-28
> **Feature branch:** `feat/phase-1-contract-foundation`
> **Base:** `origin/main` @ `07392e5` (Phase 0 docs)
> **PR target:** `main`
> **PR title:** `feat(core): establish Phase 1 contract foundation`

---

## 1. Current repository assessment

| Item | Status |
|------|--------|
| Working tree | clean (untracked: `.claude/` only) |
| `origin/main` SHA | `07392e5` (Phase 0 docs) |
| Local branch `feat/phase-1-contract-foundation` HEAD | `2efbe4f` (Phase 1 candidate — pre-existing, never pushed) |
| Pre-existing Phase 1 content | 33 files, +5,193 insertions, 5 test files, two prior commits by `tanmay-alpha` dated today |
| README encoding | **UTF-16 LE**, 2,648 bytes, no LF terminator (broken) |
| `.editorconfig` | `end_of_line = crlf` (wrong — should be `lf`) |
| `.gitattributes` | correct shape, missing `* text=auto eol=lf` precedence |
| `.gitignore` | duplicates `.env`, `.env.*`, `.venv`, `*.py[cod]`, `.coverage`, `htmlcov`, etc.; misses `.claude/settings.local.json` formatting |
| `docs/PROJECT_PLAN.md` | has only Phases 0–4 — missing 5/6/7 |
| `uv` | installed at 0.11.32 |
| Python | 3.11.9 |
| `coverage.xml` | tracked (should be ignored) |
| Pre-existing ADRs (0001/0002/0003) | marked "to be ratified in Phase 1" |

### 1a. Hard violations of the brief in the existing branch

These items will be repaired in place (do not rebuild):

1. `FlightProvider` Protocol is **sync**, brief requires **async**.
2. `FlightOperationalStatus = str`, `CabinClass = str`, `BookingState = str`, `ApprovalState = str` — bare aliases, brief requires `Literal[...]`.
3. `Money.currency` validator **silently uppercases** — brief forbids silent normalisation.
4. `DomainEvent.payload: Any` — brief requires discriminated union of typed payloads.
5. No canonical-JSON utility exists; `ApprovalRequest.payload_hash` is supplied as input but never computed.
6. `FixtureFlightProvider.health()` calls `UtcDateTime.now()` — brief forbids wall-clock in fixture content.
7. CI matrix is `3.10/3.11/3.12`, brief requires `3.11/3.12/3.13`.
8. CI actions pinned to mutable tags (`@v4`, `@v5`), brief requires immutable SHAs.
9. `scripts/check.py` does not exist.
10. `.pre-commit-config.yaml` does not exist.
11. `coverage.xml` is tracked.
12. README is UTF-16 LE with no terminator.
13. `.editorconfig` declares `crlf` globally.
14. `pyproject.toml` has `[tool.uv.build-backend]` with non-existent keys (`module-path`, `version-field`).

---

## 2. Exact scope

In scope:

- Phase 0 repair: README, `.editorconfig`, `.gitattributes`, `.gitignore`, `PROJECT_PLAN.md`.
- Python 3.11/3.12/3.13 uv-managed package `flight-agent-evaluator` v0.1.0 with `src/` layout.
- Strict Pydantic v2 contracts (`extra="forbid"`, `frozen=True`, `validate_default=True`).
- Typed `Literal` aliases for status / cabin / booking / approval states.
- Discriminated-union `DomainEvent` with typed payloads.
- Canonical-JSON utility used by `ApprovalRequest.payload_hash`.
- `FixtureFlightProvider` that is **stateless, async, deterministic, network-free**.
- Strict mypy, ruff lint+format, pytest with branch coverage ≥90%.
- `scripts/check.py` as the canonical local gate.
- `.pre-commit-config.yaml` with pinned hooks.
- GitHub Actions CI: pinned SHAs, `3.11/3.12/3.13`, lockfile check, full local gates, package-build, isolated wheel install, packaged-fixture load, `py.typed` verification.
- Documentation: `docs/architecture/phase-1-contracts.md`, ratified ADRs, updated `README.md`, updated `PROJECT_PLAN.md`.
- Independent subagent reviews (architecture / domain / reliability / security / testing).

Out of scope (Phase 1 non-goals):

- FastAPI, SQLAlchemy, Redis, MinIO, OpenTelemetry SDK, MCP SDK, LLM frameworks, Docker.
- Live provider adapters (Amadeus, OpenSky, weather).
- Scenario runner, replay engine, fault execution, assertion evaluator.
- Any web/HTTP endpoint.

---

## 3. Explicit non-goals

Re-affirmed from brief §"EXPLICIT NON-GOALS".

---

## 4. Dependency decisions

Runtime:

- `pydantic>=2.13.4,<3` (already pinned).

Development:

- `pytest>=9.1.1,<10`
- `pytest-cov>=6.0,<7`
- `ruff>=0.16.0,<1`
- `mypy>=1.16.0,<2`
- `pre-commit>=4.2.3,<5`
- `hypothesis>=6.161.8,<7`

No other runtime or dev dependency added. Each addition must be justified.

---

## 5. Package boundaries

```
src/flight_agent_evaluator/
  __init__.py             # re-exports contracts, providers, canonical_json, __version__
  py.typed
  contracts/
    __init__.py
    base.py               # ContractModel, Money, SchemaVersion, RawPayloadReference, SourceMetadata, NormalisationWarning, JsonValue (Any + JSON validator)
    common.py             # IATAAirportCode, ICAOAirportCode, IATAAirlineCode, ISOCurrencyCode, NonEmptyIdentifier, ProviderName, ToolName, SHA256Digest, IANATimezoneName, NonNegativeInt, PositiveInt, NonNegativeDuration, FlightNumber, UtcDateTime
    aviation.py           # Airport, Airline, FlightIdentity, FlightTime, FlightOperationalStatus (Literal), FlightStatus, FlightSegment, FlightStatusQuery, FlightStatusObservation, FlightSearchRequest, FlightOfferSegment, FlightOffer, FlightSearchResult, CabinClass (Literal)
    booking.py            # PassengerReference, BookingReference, BookingState (Literal), BookingSnapshot, ScopedAction, IdempotencyKey, ApprovalState (Literal), ApprovalRequest, ApprovalDecision
    providers.py          # ProviderCapability (Literal), ProviderHealthState (Literal), ProviderHealth, ProviderQuota, ProviderObservationSummary, ProviderFieldConflict, ProviderConflict
    tools.py              # ToolMutationClass (Literal), ToolCall, ToolError, ToolResultStatus (Literal), ToolResult
    tracing.py            # SpanKind (Literal), SpanStatus (Literal), RunStatus (Literal), TraceSpan, AgentRun
    events.py             # EventEnvelope, *Payload models, DomainEvent (discriminated union)
    faults.py             # ActivationRule, *Fault, FaultSpec (discriminated union)
    scenarios.py          # ScenarioIdentifier, ScenarioMetadata, ScenarioFixtureReference, ScenarioLimits, ScenarioStep, BenchmarkScenario
    evaluation.py         # *Assertion (discriminated union), AssertionStatus, AssertionOutcome, FailureCategory, FailureClassification, EvaluationStatus, EvaluationMetric, EvaluationSummary, EvaluationResult
  providers/
    __init__.py
    base.py               # FlightProvider Protocol (async, runtime_checkable)
    errors.py             # ProviderError, ProviderErrorContract, *Error subclasses
    fixture.py            # FixtureFlightProvider (async, deterministic)
  canonical.py            # canonical_json(value, *, schema_version) -> str
  resources/
    __init__.py
    fixtures/
      flight_status_delayed.json
      alternative_flights.json

tests/
  contract/
    test_canonical_json.py
    test_discriminated_unions.py
    test_schema_versions.py
  unit/
    contracts/
      test_aviation.py          # (existing, expanded)
      test_base.py              # (existing, expanded)
      test_common.py            # (existing, expanded)
      test_booking.py
      test_providers.py
      test_tools.py
      test_tracing.py
      test_events.py
      test_faults.py
      test_scenarios.py
      test_evaluation.py
    providers/
      test_errors.py            # (existing)
      test_fixture.py           # (existing, expanded)
  packaging/
    test_wheel_install.py
    test_packaged_fixtures.py
    test_py_typed.py
  smoke/
    test_public_api.py
  repo/
    test_readme_encoding.py
    test_line_endings.py
  conftest.py

scripts/
  check.py                # cross-platform local gate runner

docs/
  architecture/
    phase-1-contracts.md  # NEW (per brief)
    phase1-summary.md     # UPDATED to reflect reality
  exec-plans/
    phase-1-contract-foundation.md
  adr/
    0001-python-project-foundation.md  # RATIFIED wording
    0002-contract-versioning.md        # RATIFIED wording
    0003-deterministic-fixture-provider.md  # RATIFIED wording
    0004-canonical-json-and-approval-hashing.md  # NEW (canonical JSON policy)
    0005-async-provider-protocol.md    # NEW (async rationale)
  reports/
    phase1-final.md       # UPDATED to reflect actual state
```

Dependency direction is one-way: `contracts` → `providers/base` (only via `Protocol`). `providers/fixture` depends on `contracts`. Nothing reaches upward.

---

## 6. Contract inventory

| Module | New / Changed | Key additions |
|--------|---------------|---------------|
| `base.py` | Money.currency: drop silent uppercasing; add `JsonValue = Any` documented alias | rejection of unknown currency case |
| `common.py` | unchanged + add `SHA256Digest` (already exists) | none |
| `aviation.py` | `FlightOperationalStatus`, `CabinClass` → `Literal[...]`; add `AirportReference` (lightweight, distinct from `Airport`); keep `Airport` and `Airline` for schema realism; `FlightTime` validator rejects naive datetimes | discriminators enforced |
| `booking.py` | `BookingState`, `ApprovalState` → `Literal[...]` | typed literals |
| `providers.py` | unchanged | none |
| `tools.py` | unchanged | none |
| `tracing.py` | unchanged | none |
| `events.py` | `DomainEvent` becomes discriminated union with typed payloads (using `Annotated[Union[…], Discriminator(...)]`) | replace `payload: Any` |
| `faults.py` | unchanged (already discriminated) | none |
| `scenarios.py` | unchanged | none |
| `evaluation.py` | unchanged (already discriminated) | none |

### Invariants

- `extra="forbid"` everywhere via `ContractModel`.
- `frozen=True` everywhere via `ContractModel`.
- Naive datetimes rejected at all datetime fields.
- IATA airport `^[A-Z]{3}$`, ICAO `^[A-Z0-9]{4}$`, IATA airline `^[A-Z0-9]{2}$`, currency `^[A-Z]{3}$`.
- `Money.amount` non-negative; serialised as `str(Decimal)`.
- SHA-256 digest pattern `^[0-9a-f]{64}$`.
- `FlightSegment`: `origin != destination`; `arrival.scheduled >= departure.scheduled`.
- `FlightStatus.delay_minutes` non-negative when present.
- `ApprovalRequest.payload_hash` is computed from the `ScopedAction` payload using `canonical_json()`.

---

## 7. Canonical JSON

A narrowly scoped utility in `src/flight_agent_evaluator/canonical.py`:

- UTF-8, `sort_keys=True`, `separators=(",", ":")`.
- Decimal → string (no exponent, no scientific notation).
- datetime → ISO 8601 with explicit UTC offset (`+00:00`); documents choice.
- UUID → canonical 8-4-4-4-12 lowercase hex.
- NaN / Infinity rejected with `ValueError`.
- Non-JSON-serialisable types rejected.

Documented in **ADR 0004**. Versioned policy so historical hashes can remain stable.

---

## 8. Test strategy

Required categories (from brief):

1. Contract validation
2. Serialisation & round-trip
3. Discriminated-union parsing (events, faults, assertions)
4. Datetime rules (naive rejected; aware required)
5. Monetary rules (negative rejected, serialised as `str`)
6. Code-format rules (IATA / ICAO / airline / currency)
7. Immutability (`frozen=True`)
8. Unknown-field rejection (`extra="forbid"`)
9. Canonical-hash stability (Hypothesis-driven for boundaries)
10. Provider protocol conformance (runtime_checkable)
11. Fixture-provider determinism (≥2 parallel instances, same bytes)
12. Stable result ordering (offers by `offer_id`)
13. Typed provider errors (error_code, retryable, correlation_id)
14. Provenance & digest validation (SHA-256 of fixture bytes)
15. Resource allow-listing (path traversal rejected)
16. No shared mutation (parallel-safe)
17. Package-resource inclusion (wheel + sdist contain fixtures)
18. Wheel installation (in venv)
19. Public-API stability (imports remain stable)
20. README encoding (UTF-8, no BOM, no nulls, LF terminator)
21. Repository line-ending policy (every tracked file LF, except `.ps1`)
22. Pre-commit hook execution (subset smoke)

Target: ≥90% branch coverage on `src/flight_agent_evaluator`. Coverage is a gate, not the goal.

---

## 9. Fixture design

Existing fixtures (`flight_status_delayed.json`, `alternative_flights.json`) are retained with LF normalisation and SHA-256 recomputation.

Behaviour:

- `get_flight_status` → returns deterministic delayed flight observation.
- `search_flights` → returns ≥2 deterministic alternatives (3 in current fixture), sorted by `offer_id`.
- `health` → returns deterministic `ProviderHealth(state="healthy", checked_at=fixed datetime, ...)` — no wall-clock.
- `quota` → returns deterministic `ProviderQuota`.
- `search_flights(query)` for unknown flight → raises `ProviderDataNotFoundError`.

The fixture SHA-256 is exposed via `RawPayloadReference` and validated against a runtime-computed digest (defence against in-place tampering).

---

## 10. Packaging strategy

- `pyproject.toml` uses `uv_build` backend (already configured; will clean up non-existent `[tool.uv.build-backend]` keys).
- `uv.lock` is committed; CI runs `uv sync --locked`.
- Package data inclusion: `src/flight_agent_evaluator/resources/fixtures/*.json` and `py.typed` are auto-included by `uv_build` for src-layout packages (verified in uv docs).
- Wheel and sdist both contain fixtures and `py.typed` (verified via `python -m zipfile -l`).

---

## 11. CI strategy

Single workflow `.github/workflows/ci.yml`. Pinned third-party actions to immutable SHAs (with release-version comments). Matrix: Python `["3.11", "3.12", "3.13"]`. Steps:

1. Checkout (`actions/checkout@<sha>`).
2. Install uv (`astral-sh/setup-uv@<sha>`).
3. `uv sync --locked --all-groups`.
4. `uv lock --check` (lockfile verification).
5. Encoding & line-ending checks (Python script).
6. `uv run ruff format --check src tests scripts`.
7. `uv run ruff check src tests scripts`.
8. `uv run mypy src tests scripts`.
9. `uv run pytest --cov=flight_agent_evaluator --cov-branch --cov-report=xml`.
10. `uv build` → wheel + sdist.
11. Inspect distributions (zip listing shows `flight_agent_evaluator-0.1.0.dist-info/`, `py.typed`, fixture JSONs).
12. Isolated `uv venv + uv pip install dist/*.whl`.
13. From isolated venv, import `flight_agent_evaluator` and load each packaged fixture via `importlib.resources`.
14. Verify `py.typed` is in the wheel.
15. Concurrency cancellation, job timeout, `permissions: contents: read`.

No `pull_request_target`, no write permissions, no `secrets.*`, no mutable `@main`.

---

## 12. Security review

Verification checklist:

- No real PII, no real booking references, no API tokens, no credentials.
- No `.env` files tracked; `.gitignore` blocks future ones; `.claude/settings.local.json` ignored.
- No unsafe deserialisation (no `pickle`, no `eval`, no `yaml.load` without `SafeLoader`).
- No arbitrary code execution from JSON.
- No caller-controlled resource path: `_load_fixture` uses an allow-list of fixture names, never reads caller-supplied paths.
- No dynamic import controlled by fixture data.
- No secrets in exception strings (`safe_message` only).
- No token/header logging.
- No mutable shared fixture state.
- No hidden network access: search for `urllib`, `requests`, `httpx`, `socket` in `src/`.
- No dependency added without justification.

A fresh `code-modernization:security-auditor` subagent will be invoked. Critical / high findings fixed; medium findings fixed or documented.

---

## 13. Documentation changes

- `README.md`: valid UTF-8 no BOM, no nulls, LF; updated status line "Phase 1 — contract foundation and deterministic fixture provider complete." (gated on CI green).
- `docs/PROJECT_PLAN.md`: add Phases 5/6/7.
- `docs/architecture/phase-1-contracts.md`: NEW — module boundaries, dependency direction, contract versioning, schema migration boundary, strict validation, timestamp rules, canonicalisation policy, event envelope, provider protocol, error model, fixture provider, resource hashing, deterministic ordering, public API, security boundaries, Phase 2 extension points.
- `docs/adr/0001…0003.md`: remove "to be ratified in Phase 1" wording; mark "ratified 2026-07-28".
- `docs/adr/0004-canonical-json-and-approval-hashing.md`: NEW.
- `docs/adr/0005-async-provider-protocol.md`: NEW.
- `docs/architecture/phase1-summary.md` & `docs/reports/phase1-final.md`: rewrite to match actual tree, real test count, CI matrix, and gates.

---

## 14. Commit sequence

Conventional Commits, single linear branch, each commit green locally:

1. `chore: repair Phase 0 encoding and repository normalisation`
   - Convert README to UTF-8 LF; rewrite `.editorconfig`, `.gitattributes`, `.gitignore`; expand `PROJECT_PLAN.md` to Phases 0–7; untrack `coverage.xml`.
2. `build: initialise uv Python package and quality tooling`
   - `pyproject.toml` cleanup; `uv.lock` already present; add `scripts/check.py`; add `.pre-commit-config.yaml`.
3. `feat(core): add strict versioned domain contracts`
   - Add `Literal` aliases; discriminated-union `DomainEvent`; canonical JSON; ratification wording in ADRs 0001/0002/0003; new ADRs 0004/0005.
4. `feat(provider): add async deterministic fixture provider`
   - Convert `FlightProvider` and `FixtureFlightProvider` to async; remove wall-clock from `health`.
5. `test: verify contracts, provider, canonical JSON, and package resources`
   - Expanded tests under `tests/contract/`, `tests/packaging/`, `tests/smoke/`, `tests/repo/`; existing `tests/unit/` grown.
6. `ci: enforce Phase 1 quality gates with pinned actions and Python 3.11/3.12/3.13`
   - Rewrite `.github/workflows/ci.yml`.
7. `docs: document Phase 1 architecture and roadmap`
   - `phase-1-contracts.md`; update `README.md`, `phase1-summary.md`, `phase1-final.md`.

(Commit order may be adjusted if a cleaner dependency order surfaces during implementation.)

---

## 15. Acceptance gates (local)

All must pass:

- `uv lock --check`
- `uv sync --locked --all-groups`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src tests scripts`
- `uv run pytest --cov=flight_agent_evaluator --cov-branch`
- `uv run pre-commit run --all-files`
- `uv build`
- `uv run python scripts/check.py` (runs encoding/LF checks, ruff, mypy, pytest+coverage, build, isolated wheel install, packaged-fixture load, `py.typed` verification)
- `git diff --check`
- `git status` clean for tracked paths
- `grep -RInE "TODO|FIXME|NotImplementedError|^pass$|type: ignore|pragma: no cover|sk-[A-Za-z0-9]|api_key|password|secret|token" src tests scripts` returns nothing meaningful

---

## 16. Rollback considerations

- Branch is feature-scoped: rollback = delete `feat/phase-1-contract-foundation` (no force-push, no history rewrite).
- All changes are additive in `src/flight_agent_evaluator/`; reverting a single commit is safe if a later commit breaks something.
- `uv.lock` regenerable from `pyproject.toml`.
- Fixtures are tracked JSON; restoring original bytes from a previous commit is trivial.

---

## 17. Independent reviews

After local gates pass, dispatch **fresh** subagents (none of which wrote the code):

- `code-modernization:architecture-critic` — package boundaries, dependency direction, contract granularity, provider leakage, roadmap alignment.
- Domain reviewer (general-purpose subagent with aviation domain prompt) — codeshare modelling, timezones, departure/arrival invariants, missing-vs-unknown, price representation.
- `general-purpose` reliability reviewer — determinism, ordering, hashing, fixture byte stability, parallel safety, wall-clock dependence.
- `code-modernization:security-auditor` — path traversal, unsafe parsing, secret leakage, PII, dependency / CI safety.
- Testing reviewer — meaningful coverage, missing negative cases, weak assertions, packaging tests, cross-platform behaviour.

Every finding must contain severity, file/symbol, reasoning, corrective recommendation. Critical / high fixed; medium fixed or explicitly deferred with ADR note.

---

## 18. PR & merge

- Push `feat/phase-1-contract-foundation`.
- `gh pr create` with the prescribed PR body.
- `gh pr checks --watch`.
- Fix any CI failure root-cause locally, push, re-watch.
- Squash-merge once all gates green and reviews resolved.
- Post-merge: `git checkout main && git pull --ff-only origin main && git status && git log --oneline -10 && uv run python scripts/check.py`.

---

## 19. Definition of Done (mapped to brief §"DEFINITION OF DONE")

Reproduced from the brief and tracked as a per-item checklist during implementation.

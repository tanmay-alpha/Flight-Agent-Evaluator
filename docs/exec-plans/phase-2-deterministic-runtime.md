# Phase 2: Deterministic Runtime

## 1. Current Repository Audit

### Phase 1 state
- 3 commits: `748d478` initial, `07392e5` Phase 0 foundation, `a07890c` Phase 1 contract foundation.
- Branch `feat/phase-1-contract-foundation` merged into `main` as PR #1.
- 216 tests, 95.98% line coverage, 90%+ branch coverage.
- CI: Python 3.11, 3.12, 3.13; ruff, mypy, pytest with branch coverage gate ≥90%.
- uv-managed; `uv.lock` committed; `uv sync --locked --all-groups` verified.

### Phase 1 deliverables
- Strict Pydantic v2 contracts (contracts/aviation, booking, events, common, tools, faults, evaluation, tracing, providers).
- Canonical JSON (canonical.py, ADR 0004).
- Deterministic FixtureFlightProvider (async, network-free, importlib.resources).
- Typed provider errors (ProviderError hierarchy).
- Scripts: `scripts/check.py` (15 gates).
- Documentation: ADR 0004, ADR 0005, Phase 1 exec plan, architecture summary, final report.

### Baseline gate results (this session)
- local main == origin/main: `a07890c40c59e1ca39d24bb3d75bb1e2d2c72354`
- Working tree clean.
- `uv lock --check` passes.
- `uv sync --locked --all-groups` passes.
- `uv run pytest --collect-only -q` → 216 tests collected.
- `uv run pytest` → 216 passed, 95.98% coverage, ≥90% branch.
- PR #1 merged.

## 2. Phase 1 Compatibility Risks

### Risk: `dict[str, Any]` in runtime-boundary contracts
Fields `BenchmarkScenario.initial_state`, `ToolCall.arguments`, `ToolResult.result`, `ToolError.details` use `Any`. The existing `json_serialisable_validator` in `base.py` partially validates but is not applied to all fields.

**Mitigation**: For Phase 2, add runtime validators at the tool-executor and recording layers. Do not break existing contract surfaces; add a new `RecordingEntry` contract in `recording/contracts.py` that uses validated JSON-compatible types.

### Risk: `BenchmarkScenario.initial_state` schema
Currently unconstrained `dict[str, Any]`. Phase 2 runtime will project state snapshots from it.

**Mitigation**: Define `StateSnapshot` as a frozen Pydantic model with a `data: dict[str, Any]` field (validated JSON-compatible). The initial_state is validated through this model at scenario load time.

### Risk: FlightProvider sync vs async confusion
Documentation in `docs/reports/phase1-final.md` line 52 says "95.94% branch coverage" (stale) and some docs mention sync support.

**Mitigation**: No sync compatibility API will be added. All runtime tool calls use async.

### Risk: Recording backwards compatibility
Phase 2 introduces new recording schemas. Historical Phase 1 fixture bytes must remain readable.

**Mitigation**: No changes to fixture files. Scenario loading uses strict validation but only rejects unsupported schema versions, not unknown minor versions.

## 3. Exact Phase 2 Scope

1. Deterministic runtime primitives: VirtualClock, deterministic ID factory, RunContext.
2. Scenario loader: strict JSON loading from packaged resources and explicit local paths.
3. Typed tool system: ToolDefinition, ToolRegistry, ToolExecutor, flight.get_status, flight.search_alternatives.
4. Scripted agent driver: AgentDriver protocol, ScriptedAgentDriver, ScriptedTrajectory.
5. Coherent synthetic aviation fixture: JFK→LHR alternative flights for AS142 operating day.
6. Fault engine: deterministic fault injection per tool call.
7. Run recorder: hash-chained JSON Lines journal.
8. Replay: playback and verification modes.
9. Evaluator: objective state-based assertions producing EvaluationResult.
10. CLI: `run`, `replay`, `verify` subcommands.
11. Tests: end-to-end determinism proof, security boundaries, import-boundary checks.

## 4. Explicit Non-Goals

No live provider integrations. No databases, no cloud storage. No frontend. No LLM APIs. No MCP SDK. No FastAPI. No Docker/K8s. No async-compat shim.

## 5. Dependency Direction

```
contracts
    ↓
providers
    ↓
tools (typed tool system)
    ↓
runtime (clock, ids, context, state)
    ↓
engine (scenario_loader, tool_registry, tool_executor, fault_engine, recorder, replay, assertions, runner)
    ↓
drivers (scripted)
    ↓
CLI
```

Rules:
- contracts imports no runtime modules.
- providers imports contracts only.
- tools imports contracts + provider protocols.
- engine imports contracts + tool interfaces.
- drivers uses engine interfaces.
- CLI composes components.
- No circular imports.
- No runtime module imports CLI code.
- No provider calls bypass ToolExecutor.

## 6. Runtime Component Boundaries

### `runtime/` (no engine dependency)
- `clock.py`: VirtualClock Protocol + DeterministicVirtualClock.
- `ids.py`: DeterministicIdFactory using UUIDv5.
- `context.py`: RunContext (frozen dataclass).
- `state.py`: StateSnapshot (validated state model).

### `engine/` (no CLI dependency)
- `scenario_loader.py`: ScenarioLoader (JSON, strict validation).
- `tool_registry.py`: ToolRegistry (handler lookup, duplicate rejection).
- `tool_executor.py`: ToolExecutor (argument validation, provider dispatch, fault injection).
- `fault_engine.py`: FaultEngine (deterministic fault application).
- `recorder.py`: RunRecorder (append-only journal writer).
- `replay.py`: ReplayEngine (playback + verification modes).
- `assertions.py`: AssertionEvaluator (state-based assertions).
- `runner.py`: ScenarioRunner (orchestrates everything).

### `drivers/` (no engine internals, uses engine interfaces)
- `base.py`: AgentDriver Protocol.
- `scripted.py`: ScriptedAgentDriver + ScriptedTrajectory models.

### `tools/` (no engine dependency)
- `base.py`: ToolHandler Protocol, ToolDefinition, ToolRegistry.
- `flight.py`: flight.get_status, flight.search_alternatives handlers.

### `recording/` (no engine dependency)
- `contracts.py`: JournalEntry, RunRecording, ReplayReport, AssertionOutcome contracts.
- `journal.py`: HashChainJournal (append, verify, compute digest).
- `store.py`: FileRecordingStore (atomic writes, path validation).

## 7. Contract Changes

### New contracts in `recording/contracts.py`
- `JournalEntry`: typed payload, entry type enum, sequence number, hashes.
- `RunRecording`: run_id, scenario_id, seed, start/end times, entry count, final digest.
- `ReplayReport`: replayed entries, divergences, verification status.
- `AssertionOutcome`: assertion reference, passed, observed value, error message.

### Existing contracts: minimal changes
- Add `json_serialisable_validator` to `ToolCall.arguments` and `ToolError.details` via `field_validator`.
- `BenchmarkScenario.initial_state`: no structural change; validate via StateSnapshot at load time.
- `ToolResult.result`: no change; tool handlers validate output before constructing ToolResult.

### Versioned replacements (if breaking changes needed)
- If ToolResult.result needs typing, create `ToolResultV2` in a future version. Phase 2 uses existing fields with runtime validation.

## 8. Schema-Versioning Strategy

- Recording schema version: `1` (integer in JournalEntry).
- Scenario schema version: uses existing `SchemaVersion` (semver). Loader rejects major version > 1.
- RunRecording has its own `schema_version` field.
- Old recordings (schema version 1) are always parseable. Breaking changes increment major version and implement multi-version parsing.

## 9. Deterministic Clock Strategy

- VirtualClock Protocol: `now() -> datetime`, `advance(seconds: int) -> datetime`.
- DeterministicVirtualClock: starts at scenario reference time, advances only via `advance()`.
- Never reads `datetime.now()` or `time.time()`.
- Uses `datetime(tz=UTC)` arithmetic.
- Tool execution duration advances clock by the tool's reported duration.
- Fault delays advance clock by configured delay duration.
- Per-run isolation: each RunContext gets its own clock instance. No shared mutable state.

## 10. Deterministic Identifier Strategy

- UUIDv5 with namespace = SHA-256(namespace_bytes) truncated to UUIDv5 namespace format.
- Actually use `uuid.uuid5(uuid.NAMESPACE_DNS, deterministic_string)` where the string encodes:
  - scenario_id + scenario_version + seed + record_type + monotonic_sequence.
- Same inputs → identical UUIDs across runs with same seed.
- Different seed → different UUIDs.
- No `uuid.uuid4()` in runtime engine.
- Existing contracts retain `uuid.uuid4()` defaults; runtime explicitly supplies deterministic IDs via field_validator override or explicit construction.

## 11. Tool-Execution Lifecycle

```
ToolExecutor.execute(tool_call: ToolCall) -> ToolResult:
    1. Check tool_call limit not exceeded (from RunContext).
    2. Look up handler in ToolRegistry by tool_name.
    3. Validate arguments against ToolDefinition.input_schema.
    4. Record tool_call event in journal.
    5. Advance VirtualClock by logical_duration (0 for read-only tools).
    6. Apply FaultEngine (deterministic fault for this tool_call).
    7. If fault injected → return ToolError with fault details.
    8. Call handler.execute(arguments, provider, context).
    9. Validate handler result against ToolDefinition.output_schema.
    10. Construct ToolResult (success or failure).
    11. Record tool_result event in journal.
    12. Return ToolResult.
```

## 12. Scenario-Loading Strategy

- ScenarioLoader.load(source) where source is:
  - A packaged resource path (e.g., `"benchmark://as142-delay-scenario"`).
  - An explicit local file path (e.g., `Path("/path/to/scenario.json")`).
- Loading process:
  1. Read bytes (UTF-8, reject BOM).
  2. Reject NaN/Infinity (custom JSON decoder or Pydantic validation).
  3. Reject duplicate keys (custom JSON parser or Pydantic v2 extra=forbid on the wrapper).
  4. Enforce size limit (configurable, default 1MB).
  5. Strict Pydantic validation (extra=forbid).
  6. Reject unsupported schema major versions.
  7. Compute canonical SHA-256 of raw bytes.
  8. Resolve fixture references through allow-listed resource registry.
  9. Validate referenced fixture digests.
  10. Return validated BenchmarkScenario with digest.

## 13. Scripted-Driver Strategy

- ScriptedAgentDriver implements AgentDriver Protocol:
  - `driver_name: str` property.
  - `async run(task, tool_invoker, context) -> AgentOutput`.
- Loads `ScriptedTrajectory` from JSON (packaged or explicit path).
- Trajectory steps:
  - `InvokeToolStep`: tool_name + arguments.
  - `ProduceFinalResponseStep`: final response text.
  - `RecordCheckpointStep` (optional): state snapshot trigger.
- Scripted trajectories are deterministic test doubles, NOT benchmark ground truth.
- All tool calls flow through ToolExecutor. Driver never calls FixtureFlightProvider directly.

## 14. Recording Format

**JSON Lines** (one canonical JSON object per line).

Each line is a complete, self-contained JSON object representing one journal entry. Format:

```json
{"v":1,"seq":1,"id":"uuid5-derived","type":"run_started","run_id":"...","correlation_id":"...","time":"2026-07-28T10:00:00Z","payload":{...},"prev_hash":"...","hash":"sha256-of-this-entry"}
```

- `v`: recording schema version (integer).
- `seq`: 1-based monotonic sequence number. Gaps detected on verification.
- `id`: deterministic UUIDv5 from (run_id, type, seq).
- `type`: entry type enum string.
- `run_id`, `correlation_id`: UUID strings.
- `time`: UTC ISO 8601 from VirtualClock.
- `payload`: typed payload specific to entry type (JSON-compatible).
- `prev_hash`: hex SHA-256 of previous entry's canonical form (empty string for first entry).
- `hash`: hex SHA-256 of this entry's canonical form (everything except `hash` field itself, serialized deterministically).

**Final digest**: SHA-256 of the canonical concatenation of all entry hashes, joined by `\n`, with a trailing `\n`. This produces a single 64-character hex string that identifies the entire recording.

## 15. Hash-Chain Design

- Each entry's `hash` is computed from its canonical representation (all fields except `hash`, sorted keys, UTC timestamps, no whitespace variation).
- `prev_hash` links to the previous entry's `hash`.
- Verification: re-derive each entry's hash, check `prev_hash` chain, check sequence monotonicity, check no gaps.
- Tampering detection: any change to any entry's payload, type, time, or sequence invalidates the chain from that point forward.
- No cryptographic authentication (no signing). SHA-256 detects alteration but does not prove authorship.

## 16. Replay Modes

### Playback mode
- Read journal entries sequentially.
- Re-emit tool_call entries through ToolExecutor (using the same provider).
- Compare re-issued tool results with recorded tool_result entries.
- Report divergences (mismatched results, unexpected errors, timing differences).

### Verification mode
- Read journal entries.
- Verify hash chain (no execution).
- Verify sequence completeness.
- Report verification status (valid / tampered).

## 17. Divergence Detection

- After replay, compare each re-executed ToolResult with the recorded ToolResult.
- Divergence types:
  - `status_mismatch`: re-executed status differs from recorded.
  - `result_mismatch`: re-executed result payload differs (byte-identical canonical JSON comparison).
  - `error_mismatch`: re-executed error differs from recorded.
  - `missing_tool`: tool call in journal but handler not registered.
  - `extra_tool`: tool call executed but not in journal.
  - `timing_divergence`: clock position differs (informational, not a failure by default).

## 18. Fault Semantics

- Faults are configured in BenchmarkScenario.faults.
- FaultEngine applies faults deterministically based on (scenario_seed, tool_name, call_sequence).
- Supported fault types:
  - `provider_unavailable`: ProviderUnavailableError.
  - `timeout`: ToolError with type "timeout".
  - `invalid_response`: ProviderInvalidResponseError mapped to ToolError.
  - `rate_limited`: ProviderQuotaExceededError mapped to ToolError.
- Fault probability: deterministic (seed-based), not random.
- Faults are recorded in the journal as fault_injected events.

## 19. Assertion Semantics

- Assertions defined in BenchmarkScenario.assertions.
- AssertionEvaluator runs after scenario completion.
- Assertion types:
  - `state_equals`: projected state matches expected value.
  - `state_contains`: projected state contains expected key/value.
  - `tool_called`: specific tool was called with expected arguments.
  - `tool_not_called`: specific tool was not called.
  - `no_error`: no tool errors occurred.
- Results: AssertionOutcome (passed, observed value, error message).
- All assertions produce an EvaluationResult with overall pass/fail.

## 20. State-Projection Semantics

- StateProjection extracts a structured view from the run's journal.
- Projections:
  - `last_tool_result`: result of the most recent successful tool call.
  - `all_tool_calls`: list of all tool calls made.
  - `tool_call_count`: count of tool calls.
  - `errors`: list of all tool errors.
  - `custom`: user-defined projection from initial_state + tool results.
- Projections are deterministic functions of the journal (no re-execution).

## 21. Fixture Extensions

- Add `jfk_lhr_alternative_flights.json` fixture for JFK→LHR on 2026-07-28.
- Extend KNOWN_SEARCH_FIXTURES with `JFK-LHR-2026-07-28` key.
- Preserve existing `JFK-LAX-2026-07-28` fixture.
- Allow-listed resource registry maps query keys to fixture files and expected digests.

## 22. CLI Design

```
flight-eval run <scenario> [--seed N] [--output DIR] [--trajectory PATH]
flight-eval replay <recording> [--output DIR]
flight-eval verify <recording>
```

Entry point: `src/flight_agent_evaluator/cli.py` with `main()` function.
Registered in `pyproject.toml` as `flight-eval` console script.

## 23. Security Controls

- Scenario loading: reject paths outside explicit root, reject symlinks, enforce size limits, no BOM.
- Recording store: atomic writes (temp + rename), no path traversal, no symlink escape, no caller-controlled filenames.
- No credentials, paths, or machine names in recordings.
- Tool errors: no raw tracebacks in machine-readable results, no secrets.
- Fault injection: no arbitrary code execution, only configured fault types.

## 24. Test Strategy

### Unit tests (per module)
- Clock: advance, no wall-clock, negative advance rejection, UTC enforcement.
- IDs: deterministic UUIDv5, seed independence, cross-platform stability.
- RunContext: immutability, field validation.
- ScenarioLoader: strict JSON, size limits, version rejection, fixture resolution.
- ToolRegistry: duplicate rejection, unknown tool errors.
- ToolExecutor: argument validation, provider dispatch, fault injection, limit enforcement.
- FaultEngine: deterministic fault application.
- Recorder: append, hash chain, sequence gaps, reordering detection.
- Replay: playback divergence detection, verification mode.
- Assertions: state projection, assertion evaluation.

### Integration tests
- End-to-end scenario execution → deterministic recording (byte-identical across runs).
- End-to-end replay → verification passes, playback detects injected divergences.
- Fault injection → recorded faults, replayed correctly.
- Evaluation → assertions evaluated against projected state.

### Security tests
- Scenario path traversal rejection.
- Recording store atomicity and path safety.
- No secrets in error messages.
- Hash-chain tampering detection.

### Determinism proof test
- Run same scenario 3 times with same seed.
- Assert recordings are byte-identical (canonical JSON comparison).
- Assert EvaluationResults are identical.

### Import-boundary test
- Static analysis: no circular imports, no runtime imports CLI, no provider bypasses tool boundary.

## 25. Commit Sequence

1. `docs: plan Phase 2 deterministic runtime`
2. `feat(runtime): add deterministic clock, IDs, and run context`
3. `feat(contracts): add recording and trajectory contracts`
4. `feat(scenarios): add strict scenario and trajectory loader`
5. `feat(fixtures): add JFK-LHR coherent alternative flight fixture`
6. `feat(tools): add typed registry and aviation tool handlers`
7. `feat(engine): add fault engine and tool executor`
8. `feat(recording): add hash-chained run journal and file store`
9. `feat(replay): add playback and verification replay modes`
10. `feat(evaluation): add assertion evaluator and state projection`
11. `feat(runner): add scenario runner orchestrating all components`
12. `feat(drivers): add scripted agent driver`
13. `feat(cli): expose run, replay, and verify commands`
14. `test: verify end-to-end determinism and security boundaries`
15. `test: verify import boundaries and API compatibility`
16. `docs: document Phase 2 architecture and verified results`

## 26. Migration and Rollback Risks

- Phase 2 introduces new packages (runtime/, engine/, drivers/, tools/, recording/). Existing Phase 1 code is untouched.
- New CLI entry point (`flight-eval`) does not conflict with existing scripts.
- Recording schema is versioned (v1). Old recordings remain parseable.
- Contract changes are additive (new contracts in recording/). Existing contracts unchanged.
- Rollback: delete Phase 2 branch, main remains at Phase 1 state.

## 27. Definition of Done

- [ ] `git fetch && git switch main && git pull` → clean tree, on `a07890c`.
- [ ] Feature branch `feat/phase-2-deterministic-runtime` created from main.
- [ ] All Phase 1 tests still pass (216 tests, ≥90% coverage).
- [ ] New runtime tests pass with ≥90% coverage on new modules.
- [ ] End-to-end determinism proof: 3 identical runs produce byte-identical recordings.
- [ ] Hash-chain verification passes on all test recordings.
- [ ] Replay playback detects injected divergences.
- [ ] Fault injection produces deterministic, recorded faults.
- [ ] Assertion evaluator correctly passes/fails against projected state.
- [ ] CLI `run`, `replay`, `verify` commands work end-to-end.
- [ ] Import boundary check passes (no circular imports, no provider bypass).
- [ ] Security tests pass (path traversal, atomic writes, no secrets in errors).
- [ ] CI green on Python 3.11, 3.12, 3.13.
- [ ] PR #2 created and merged to main.
- [ ] Phase 1 report updated with correct metrics (216 tests, 95.98% coverage).

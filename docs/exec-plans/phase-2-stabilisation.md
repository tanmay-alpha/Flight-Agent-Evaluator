# Phase 2 Stabilisation Plan

> **Branch**: `feat/phase-2-deterministic-runtime` (current HEAD: `7d7d6cf`)
> **Date**: 2026-07-29
> **Status**: Plan — awaiting approval

## 0. Audit Summary

Four parallel audits (architecture+contracts, runtime primitives, engine components, tools abstractions, recording/replay) found **37 verified defects** across the codebase. They break down into:

| Severity | Count | Key issues |
|---|---|---|
| **CRITICAL** | 8 | Will crash or produce wrong output on any run |
| **HIGH** | 13 | Functional bugs that silently produce incorrect results |
| **MEDIUM** | 16 | Design gaps, dead code, stubs |

No Phase 1 files or tests were touched. All repairs are confined to Phase 2 modules.

---

## 1. Critical Fixes (must fix before anything else works)

### 1.1 FaultEngine ↔ contract schema mismatch

**Files**: `engine/fault_engine.py:57-67`, `contracts/faults.py:37-123`

The engine reads attributes that don't exist on the contract models:

| Engine reads | Contract provides | Fix |
|---|---|---|
| `fault.tool_name` | `fault.target_tool` | Engine → `fault.target_tool` |
| `fault.enabled` | *(missing)* | Add `enabled: bool = True` to all fault models |
| `fault.fault_id` | *(missing)* | Add `fault_id: NonEmptyIdentifier` to all fault models |
| `fault.probability` | *(missing)* | Add `probability: float = Field(ge=0.0, le=1.0)` |
| `fault.fault_type == "provider_unavailable"` | `"provider_server_error"` | Engine → `"provider_server_error"` |
| `fault.fault_type == "invalid_response"` | `"malformed_response"` | Engine → `"malformed_response"` |
| `fault.fault_type == "rate_limited"` | `"rate_limit"` | Engine → `"rate_limit"` |

Additionally, the engine ignores `ActivationRule` entirely (always-on probability). The engine must dispatch on `activation.kind` instead of a flat probability check. At minimum, implement `"always"` activation now and leave other kinds for later.

### 1.2 VirtualClock Protocol instantiated as concrete class

**Files**: `cli/main.py:29`, `engine/runner.py:37,57`

`VirtualClock` is a `typing.Protocol` — it cannot be instantiated. The CLI does `clock = VirtualClock()` which raises `TypeError`. Fix: CLI must construct `DeterministicVirtualClock(start=...)` using the scenario's reference time. The runner already accepts a `VirtualClock` instance via its constructor, so this is only a CLI-side bug.

### 1.3 Hardcoded placeholder ID factory in CLI

**Files**: `cli/main.py:35-38`

```python
id_factory = DeterministicIdFactory(
    scenario_id="init",    # ← placeholder
    scenario_version=1,    # ← placeholder
    seed=0,                # ← placeholder
)
```

Must derive from `loaded.scenario.scenario_id.id`, `.version`, and `.seed`.

### 1.4 ToolCall uses uuid4 default (non-deterministic)

**File**: `contracts/tools.py:39`

```python
call_id: uuid.UUID = Field(default_factory=uuid.uuid4)
```

The contract itself produces non-deterministic IDs. The scripted driver overrides `call_id` with a deterministic UUID derived from the ID factory, but any direct construction of `ToolCall()` gets a uuid4. Fix: remove the `default_factory=uuid.uuid4` and require `call_id` to be explicitly provided (or set it from the ID factory at construction time in the driver).

### 1.5 `tools/base.py` references undefined `Protocol`

**File**: `tools/base.py:19`

```python
class ToolHandler(Protocol):
```

`Protocol` is never imported in this file. Mypy/pyright will flag this as an unresolved name. Runtime works only because concrete handlers don't subclass `ToolHandler` — they satisfy it structurally. Fix: add `from typing import Protocol` to the imports.

### 1.6 `tools/__init__.py` exports non-existent symbol

**File**: `tools/__init__.py:12-21`

```python
from flight_agent_evaluator.tools.flight import (
    FlightGetStatusHandler,
    FlightSearchAlternativesHandler,  # ← does not exist
    register_default_tools,
)
```

The actual class in `tools/flight.py` is named `FlightSearchHandler` (line 99), not `FlightSearchAlternativesHandler`. Importing `flight_agent_evaluator.tools` raises `ImportError`. Fix: rename import to `FlightSearchHandler` to match the definition.

### 1.7 `ReplayReport.recording_run_id` type mismatch crashes on every verify()

**File**: `replay/engine.py:71`, `recording/contracts.py:129`

`ReplayReport.recording_run_id` is typed as `uuid.UUID`, but `ReplayEngine.verify()` passes a plain `str` (`run_id` parameter). Pydantic raises `ValidationError` on every successful chain verification. Fix: change `ReplayReport.recording_run_id` to `NonEmptyIdentifier` (or `str`) to match the engine.

### 1.8 `ReplayEngine.verify()` never re-executes tools despite docstring promise

**File**: `replay/engine.py:43-76`

The class docstring and `ReplayReport.status` literal `"diverged"` imply that verification re-invokes tool calls and compares outputs. The implementation only checks the hash chain — it never constructs a `ProviderRunner`, never re-executes, and never produces `"diverged"` (only `"verified"` or `"tampered"`). The `if not chain_valid:` branch at line 60 is dead code because `journal.verify()` raises on failure rather than returning `False`. Fix: implement tool re-execution in verification mode, producing real `diverged` outcomes when recorded results differ from live results. Phase 2 scope: at minimum re-execute `tool_call` entries. Phase 3: full divergence classification.

---

## 2. High Fixes (functional bugs)

### 2.1 Empty hardcoded trajectory in runner

**File**: `engine/runner.py:91-98`

The runner creates `ScriptedTrajectory(steps=())` and never reads a trajectory from the loaded scenario. Since `ScriptedTrajectory` has a validator that rejects empty steps, this currently **crashes on construction**. Fix: derive the trajectory from `loaded.scenario.steps` (convert `ScenarioStep` → trajectory steps), or load it from a trajectory reference in the scenario.

### 2.2 Journal created but never populated

**Files**: `engine/runner.py:58`, `engine/scripted.py:84`

The runner creates `HashChainJournal()` at line 58 but the driver passes `journal=None` to the executor at line 84. The journal entry count is always 0 and the final digest is always the empty-journal hash. Fix: pass the journal through to the executor and have the executor append entries for each tool call and result.

### 2.3 Scripted driver mutates frozen StateSnapshot in-place

**File**: `engine/scripted.py:90`

```python
state.data.setdefault("tool_calls", []).append({...})
```

`StateSnapshot` is `frozen=True` but Pydantic's freeze is shallow — it prevents field reassignment but not in-place dict mutation. This silently bypasses immutability. Fix: produce a new `StateSnapshot` with updated data instead of mutating the dict:

```python
new_data = dict(state.data)
new_data.setdefault("tool_calls", []).append({...})
state = state.model_copy(update={"data": new_data})
```

### 2.4 Scripted driver sync asyncio bridge

**File**: `engine/scripted.py:73-86`

```python
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
result = loop.run_until_complete(executor.execute(...))
```

This crashes with `RuntimeError: This event loop is already running` when called inside pytest-asyncio or any outer `asyncio.run()`. Fix: make `ScriptedAgentDriver.execute` an `async def` and have callers `await` it. The runner must also become async.

### 2.5 AssertionEvaluator return value discarded

**File**: `engine/runner.py:109-115`

```python
self._evaluator.evaluate(
    scenario=scenario, state=state, run_id=run_id,
    started_at=start, ended_at=end,
)
```

The return value (an `EvaluationResult`) is not stored or returned. `RunRecording` has no evaluation fields. Fix: add evaluation fields to `RunRecording` (or return the `EvaluationResult` alongside it), and include them in the persisted recording.

### 2.6 ScenarioLoader silently accepts duplicate JSON keys

**File**: `engine/scenario_loader.py:99-105`

Standard `json.loads` keeps the last value for duplicate keys. The comment at line 99-101 incorrectly claims Pydantic `extra="forbid"` catches this — it doesn't; it only catches keys not declared on the model. Fix: use `json.loads(raw, object_pairs_hook=list)` and detect duplicate keys, raising `ScenarioLoaderError`.

### 2.7 ScenarioLoader path-safety opt-in only

**File**: `engine/scenario_loader.py:137-143`

```python
def _check_path_safety(self, path: Path) -> None:
    if self._allowed_root is None:
        return  # ← any existing non-symlink path is accepted
```

Path traversal is only enforced when `allowed_root` is explicitly set. The CLI never sets one. Fix: enforce path safety unconditionally by default, or always require an explicit `allowed_root`.

### 2.8 ReplayEngine is a stub

**File**: `replay/engine.py:43-90`

- `verify()` only checks the hash chain and reports "tampered" for chain failures — it doesn't re-execute tools or compare results
- `playback()` returns raw dict entries without re-execution
- No divergence detection against replayed tool results

Fix for Phase 2: implement hash-chain verification (already done) + at minimum replay tool_call entries through the executor and compare results. Full divergence detection is Phase 3 scope.

### 2.9 `tool_executor.py` duplicates `tools/base.py` definitions

**File**: `engine/tool_executor.py:16,39-118`

`ToolHandler`, `ToolDefinition`, and `ToolRegistry` are defined identically in both `tools/base.py` and `engine/tool_executor.py`. The duplicates are NOT identical — they drift in type annotations (`context: RunContext` vs `context: Any`, `mutation_class: Literal` vs `str`). Fix: remove the three class definitions from `tool_executor.py` and import them from `tools.base`. Also remove unused `BaseModel` and `uuid` imports from `tool_executor.py`.

### 2.10 Runner leaks wall-clock timestamps into recordings

**File**: `engine/runner.py:57,108`

```python
start = datetime.now(UTC)  # ← wall-clock
end = datetime.now(UTC)    # ← wall-clock
```

`RunRecording.started_at` and `completed_at` are populated from `datetime.now(UTC)`, not from `self._clock.now()`. This breaks the determinism guarantee — two identical runs at different wall-clock times produce different recordings. Fix: use `self._clock.now()` for both timestamps.

### 2.11 Runner uses `uuid.uuid4()` for `trajectory_id`

**File**: `engine/runner.py:95

```python
trajectory_id=uuid.uuid4(),
```

A randomly generated UUID appears in the recording, breaking byte-identical reproducibility. Fix: derive `trajectory_id` from the deterministic ID factory: `self._id_factory.next(record_type="trajectory", sequence=0)`.

### 2.12 `RunRecording` timestamps not timezone-aware

**File**: `recording/contracts.py:96-97`

`JournalEntry.time` enforces timezone-awareness via `_require_timezone_aware`, but `RunRecording.started_at` and `completed_at` accept naive datetimes. Inconsistent: the journal-level timestamps are tz-aware but the summary metadata can be naive. JSON serialisation will differ between processes, breaking cross-host digest comparison. Fix: apply the same `_require_timezone_aware` validator to `RunRecording.started_at` and `completed_at`.

### 2.13 `playback()` returns tampered data without verification

**File**: `replay/engine.py:78-90`

`playback()` calls `HashChainJournal.read_jsonl(path)` (no validation) and returns the entries + digest. It does not call `journal.verify()`. A caller using playback for reporting gets tampered entries with a digest that won't match what a verifier would compute. Fix: have `playback()` call `verify()` first and translate `JournalVerificationError` into a result shape (e.g., return `{"run_id": ..., "entries": [], "digest": "...", "tampered": True}`) or raise.

---

## 3. Medium Fixes (design gaps, dead code)

### 3.1 Unused `_RawStateData` class

**File**: `runtime/state.py:42-44`

Dead code. Remove it.

### 3.2 Unnecessary UUID round-trip in runner

**File**: `engine/runner.py:65-78`

```python
run_id = str(self._id_factory.next(record_type="run", sequence=0))
# ...
run_id=uuid.UUID(run_id),
```

Convert to UUID once at construction, pass the UUID object throughout.

### 3.3 ToolCall.call_id must be set by driver

**File**: `engine/scripted.py:63-72`

The driver constructs ToolCall without `run_id`. Fix: set `run_id=context.run_id` on the ToolCall.

### 3.4 Add `enabled` field to fault models

Per fix 1.1, all 8 fault types need `enabled: bool = True`.

### 3.5 Add `fault_id` field to fault models

Per fix 1.1, all 8 fault types need `fault_id: NonEmptyIdentifier`.

### 3.6 Add `probability` field to fault models

Per fix 1.1, all 8 fault types need `probability: float = Field(ge=0.0, le=1.0)`.

### 3.7 Log warnings for skipped assertions

The `AssertionEvaluator` silently returns `"skipped"` for most assertion types. Add logging so test failures are diagnosable.

### 3.8 Immutable state transitions

The driver mutates `state.data` in-place (fix 2.3). Extend this to ensure all runtime code paths use `model_copy(update=...)` rather than in-place mutation.

### 3.9 Dead code: `EMPTY_HASH` constant and unused `json` import

**File**: `recording/journal.py:23`, `replay/engine.py:16`

`EMPTY_HASH = "0" * 64` in `journal.py` is declared but never referenced. The genesis prev_hash is `""`, not `"0"*64`. Remove the dead constant or document it as the canonical genesis sentinel and use it everywhere. Also: `replay/engine.py` imports `json` (line 16) but never uses it.

### 3.10 `verify()` return type misleading

**File**: `recording/journal.py:117`

`verify()` is typed `-> bool` but returns only `True` (failure raises `JournalVerificationError`). Change return type to `None` to reflect that success is signalled by the absence of an exception.

### 3.11 `_canonicalise_payload` allows NaN/Infinity in journal hashes

**File**: `recording/journal.py:28`

`json.dumps(...)` is called without `allow_nan=False`. Python's permissive default serialises `NaN`, `Infinity`, `-Infinity` as bare words (not valid JSON). Hashes stay consistent within a Python process but an external re-serialiser using strict JSON would produce different bytes, breaking the chain. Fix: pass `allow_nan=False` to reject non-finite floats at journal construction time.

### 3.12 `ReplayEngine` has no `run_id` sanitisation (path traversal)

**File**: `replay/engine.py:54,83`

`self._root / f"{run_id}.jsonl"` is built directly from caller input with no separator or traversal check. `FileRecordingStore` has `_sanitise_run_id` but the replay engine never calls it. Fix: call `_sanitise_run_id` (or inline equivalent) before constructing the path.

### 3.13 `_sanitise_run_id` does not reject NUL bytes or Windows-reserved chars

**File**: `recording/store.py:58-74`

Path traversal is blocked but `\0`, `<>:"|?*`, and control characters pass through. On Windows these produce `OSError` at file-open time. Add an allow-list regex (e.g. `^[A-Za-z0-9._\-]+$`).

### 3.14 `RunRecording` has no entry_count / digest consistency validator

**File**: `recording/contracts.py:94-97`

`entry_count` and `final_digest` on `RunRecording` are not cross-validated against the on-disk journal. A consumer reading `<run_id>.meta.json` cannot trust the summary without calling `verify()` + `final_digest()` independently. Document the trust model or add a validator.

### 3.15 `BookingSnapshot` has redundant `currency` field

**File**: `contracts/booking.py:61`

`BookingSnapshot` has both `total_price: Money` (which contains `amount` and `currency`) and a separate `currency: str`. No validator ensures they match. If they diverge, downstream consumers cannot know which is canonical. Fix: remove `currency` and source it from `total_price.currency`.

---

## 4. Repair Sequence

Repairs are ordered by dependency — later fixes depend on earlier ones.

| # | Repair | Depends on |
|---|---|---|
| 1 | FaultEngine schema alignment (1.1) | — |
| 2 | Add `Protocol` import in `tools/base.py` (1.5) | — |
| 3 | Fix `tools/__init__.py` export name (1.6) | — |
| 4 | Remove duplicate ToolHandler/ToolDefinition/ToolRegistry from `tool_executor.py` (2.9) | 2 |
| 5 | ToolCall uuid4 default → explicit call_id (1.4) | — |
| 6 | VirtualClock instantiation in CLI (1.2) | — |
| 7 | Hardcoded ID factory in CLI (1.3) | 6 |
| 8 | ScenarioLoader duplicate keys (2.6) | — |
| 9 | ScenarioLoader path safety (2.7) | — |
| 10 | Empty trajectory in runner (2.1) | — |
| 11 | Journal wiring — pass journal to executor (2.2) | 10 |
| 12 | Scripted driver asyncio bridge → async (2.4) | 11 |
| 13 | StateSnapshot immutability (2.3, 3.8) | 12 |
| 14 | AssertionEvaluator → RunRecording (2.5) | 10 |
| 15 | ReplayEngine real verification (2.8) | 11 |
| 16 | Dead code removal (3.1) | — |
| 17 | UUID round-trip cleanup (3.2) | 10 |
| 18 | ToolCall.run_id in driver (3.3) | 5 |
| 19 | Fault model fields: enabled, fault_id, probability (1.1, 3.4-3.6) | 1 |
| 20 | Assertion logging (3.7) | 14 |
| 21 | Runner wall-clock timestamps → virtual clock (2.10) | 10 |
| 22 | Runner trajectory_id → deterministic factory (2.11) | 10 |
| 23 | ReplayReport.recording_run_id type fix (1.7) | — |
| 24 | ReplayEngine verify() re-executes tools (1.8) | 11 |
| 25 | RunRecording tz-aware validator (2.12) | — |
| 26 | ReplayEngine playback() verifies chain (2.13) | 24 |
| 27 | Dead code: EMPTY_HASH + unused json import (3.9) | — |
| 28 | verify() return type to None (3.10) | — |
| 29 | _canonicalise_payload allow_nan=False (3.11) | — |
| 30 | ReplayEngine run_id sanitisation (3.12) | — |
| 31 | _sanitise_run_id charset restriction (3.13) | — |
| 32 | RunRecording entry_count/digest validator (3.14) | 25 |
| 33 | BookingSnapshot redundant currency field (3.15) | — |

---

## 5. Test Strategy

### TDD approach
Write failing tests first, then fix the code to make them pass.

### New test modules

| Module | Tests |
|---|---|
| `tests/unit/engine/test_fault_engine.py` | Schema alignment: fault engine reads contract fields correctly, activation rules dispatch, probability determinism |
| `tests/unit/engine/test_runner.py` | Runner creates journal, passes it to driver, trajectory from scenario, evaluation in recording |
| `tests/unit/engine/test_scripted_driver.py` | Async driver, no in-place state mutation, ToolCall has run_id, journal appends |
| `tests/unit/cli/test_main.py` | CLI constructs DeterministicVirtualClock, derives IDs from scenario, error handling |
| `tests/unit/engine/test_scenario_loader_strict.py` | Duplicate key rejection, path traversal rejection, timezone validation |
| `tests/unit/replay/test_engine.py` | Replay with real verification, divergence detection |
| `tests/unit/contracts/test_tools_deterministic.py` | ToolCall construction without uuid4, run_id requirement |

### Existing test updates
- `test_determinism.py` — update to use scenario-derived trajectories and verify non-empty recordings
- `test_primitives.py` — add Protocol conformance test for VirtualClock
- `test_scenario_loader.py` — add duplicate key and path traversal tests

### Acceptance gates
1. `uv run pytest` — all existing tests still pass (no Phase 1 breakage)
2. New tests: ≥90% branch coverage on new/changed Phase 2 code
3. `uv run ruff check src/ tests/` — zero errors
4. `uv run mypy src/ tests/` — zero errors
5. Determinism proof: 3 runs with same seed produce byte-identical recordings
6. E2E pipeline: `run → replay → verify` passes end-to-end

---

## 6. File Change Summary

| File | Action |
|---|---|
| `contracts/faults.py` | Add `enabled`, `fault_id`, `probability` to all 8 fault types |
| `contracts/tools.py` | Remove uuid4 default from `call_id` |
| `engine/fault_engine.py` | Align field names with contracts, dispatch on `activation.kind` |
| `engine/scenario_loader.py` | Reject duplicate keys, enforce path safety unconditionally |
| `engine/runner.py` | Derive trajectory from scenario, wire journal, async, include evaluation |
| `engine/scripted.py` | Make async, fix state immutability, set run_id on ToolCall |
| `engine/tool_executor.py` | Remove duplicate ToolHandler/ToolDefinition/ToolRegistry, add imports |
| `replay/engine.py` | Real tool re-execution in verification mode |
| `runtime/state.py` | Remove unused `_RawStateData` |
| `cli/main.py` | Use `DeterministicVirtualClock`, derive IDs from loaded scenario |
| `tools/base.py` | Add `Protocol` import, remove unused `BaseModel` import |
| `tools/__init__.py` | Fix export: `FlightSearchAlternativesHandler` → `FlightSearchHandler` |
| `recording/contracts.py` | Add evaluation fields to `RunRecording` |
| `tests/unit/engine/test_fault_engine.py` | **New** |
| `tests/unit/engine/test_runner.py` | **New** |
| `tests/unit/engine/test_scripted_driver.py` | **New** |
| `tests/unit/cli/test_main.py` | **New** |
| `tests/unit/engine/test_scenario_loader_strict.py` | **New** |
| `tests/unit/replay/test_engine.py` | **New** |
| `tests/unit/contracts/test_tools_deterministic.py` | **New** |
| `tests/unit/tools/test_tools_imports.py` | **New** |
| `tests/unit/replay/test_replay_report_types.py` | **New** — ReplayReport field types match engine output |
| `tests/unit/replay/test_playback_verify.py` | **New** — playback calls verify() |
| `tests/unit/recording/test_run_recording_tz.py` | **New** — tz-aware validator on RunRecording |
| `tests/unit/replay/test_engine_verify_execution.py` | **New** — verify() re-executes tools |
| `tests/unit/recording/test_store_sanitise.py` | **New** — _sanitise_run_id rejects NUL and reserved chars |
| `tests/unit/recording/test_journal_nan.py` | **New** — _canonicalise_payload rejects NaN |

---

## 7. Non-Goals (deferred to Phase 3)

- Full divergence detection (status/result/error/timing mismatches)
- Activation rules beyond `"always"` (`after_n_calls`, `on_match`, `time_window`)
- State projector module (`StateProjector` with `last_tool_result`, `all_tool_calls`, etc.)
- Replay re-execution against live provider
- Cryptographic signing of recordings
- Recording schema versioning beyond v1

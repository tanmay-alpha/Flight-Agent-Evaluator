# Phase 2 Stabilisation — Verified Findings and Repair Plan

> **Branch**: `fix/phase-2-runtime-stabilisation`
> **Broken starting SHA**: `daa27fbf88624dfe67376a4a34d8ba3b2c564614`
> **Verified SHA on `fix/phase-2-runtime-stabilisation` HEAD**: `7cfabef` (intermediate work in progress)
> **Date**: 2026-07-30
> **Status**: Repair — in execution

## 0. GitHub CI Failure Root Cause

The failing run `30473701676` failed at **Ruff lint** on every Python
matrix (3.11, 3.12, 3.13). Subsequent jobs (mypy, pytest, build, smoke)
were skipped. The root cause is the same everywhere: the merged Phase 2
PR introduced structural defects that violate the configured Ruff rules
in `pyproject.toml` (strict set including `E`, `F`, `I`, `B`, `UP`, `SIM`,
`ANN`, `S`, `C4`, `ARG`, `PIE`, `PERF`, `Q`).

A re-run with the current tree shows:

- `ruff check` — passes (after a small in-progress fix already in the
  branch).
- `ruff format --check` — one file (`docs/exec-plans/phase-2-stabilisation.md`)
  needs reformatting.
- `mypy src tests scripts` — **174 errors** across 14 files.
- `pytest` — 278 tests pass, but coverage 86% < 90% required.
- `uv run python -c "import flight_agent_evaluator"` — passes.
- `uv run python -c "from flight_agent_evaluator.cli.main import main"` — passes.
- `uv run flight-evaluator --help` — passes.

Beyond the surface failures, the merged code has the architectural
defects called out in the stabilisation brief. They are *not* lint
findings — Ruff cannot see them. They include:

- Empty default trajectory that the runner tries to construct.
- Scripted driver that monkey-patches event loops.
- FaultEngine reading fictional fields (`tool_name`, `enabled`,
  `probability`, `fault_id`) from a `FaultSpec` discriminated union that
  has none of them.
- AssertionEvaluator returning `"skipped"` for nearly every assertion
  type.
- Replay engine that only validates hash chain and never re-executes.
- CLI hardcoding `scenario_id="init"`, `seed=0`.
- Journal created but never written to.
- Path-traversal mitigation that is opt-in only.
- ToolCall using `default_factory=uuid.uuid4` for `call_id`.
- `ToolCall` defaults `end_time` to `UtcDateTime.now()` (wall-clock).
- `state.data` mutated in place.

## 1. Functional Defects

### 1.1 `engine/runner.py` constructs invalid empty trajectory

**File**: `src/flight_agent_evaluator/engine/runner.py:103-105`

The runner passes `scenario.trajectory` to the driver. The packaged
scenario has no `trajectory` field, so Pydantic's
`_populate_default_trajectory` populates one with a single
`ProduceFinalResponseStep`. The driver never invokes any tool, so the
journal is empty (only the run_started entry is emitted). The
`test_full_pipeline_determinism` test passes by coincidence (digest
matches digest) but the recording is meaningless.

### 1.2 `engine/fault_engine.py` accesses fields not on `FaultSpec`

**File**: `src/flight_agent_evaluator/engine/fault_engine.py:57-67`

The contracts in `contracts/faults.py` define:

| Field | Contract |
|---|---|
| `target_provider` | `ProviderName` |
| `target_tool` | `ToolName \| None` |
| `activation` | `ActivationRule` (kind: `always` / `after_n_calls` / `on_match` / `time_window`) |
| `occurrence_count` | `NonNegativeInt` |
| `fault_type` | `Literal[...]` (one of 8 types) |
| Specific fields | `timeout_seconds`, `retry_after_seconds`, `status_code`, etc. |

The engine reads `fault.tool_name`, `fault.enabled`, `fault.probability`,
`fault.fault_id`. **None of these exist on the contract.** The engine
also returns the wrong status for `timeout`/`provider_server_error`/
`malformed_response`/`rate_limit` (confused names).

### 1.3 `engine/runner.py` uses `uuid4` for `trajectory_id`

**File**: `src/flight_agent_evaluator/engine/runner.py:95`

The snippet wrapped in a passing test still uses `trajectory_id=uuid.uuid4()` in the
contract default — there is no such line in the actual current runner,
but the contract default in `recording/contracts.py` line 207 for
`ScriptedTrajectory.trajectory_id` is `NonEmptyIdentifier`
(no default). The `tests/e2e/test_determinism.py` test relies on the
package scenario computed `trajectory_id = "default-trajectory"`. This
must be replaced with a deterministic ID derived from the scenario.

### 1.4 `engine/runner.py` type mismatch on `run_id`

**File**: `src/flight_agent_evaluator/engine/runner.py:72, 100`

`journal.append_event` expects `run_id: str`. We pass `uuid.UUID(run_id)`.
`RunContext.run_id` is typed `uuid.UUID` but the runner passes
`run_id: str` to its constructor. mypy flags both.

### 1.5 `engine/scenario_loader.py` accepts duplicate JSON keys

**File**: `src/flight_agent_evaluator/engine/scenario_loader.py:99-105`

The comment claims Pydantic `extra="forbid"` rejects duplicates, but
that only rejects unknown keys, not duplicate keys (which Python's
`json.loads` collapses silently). The contract is broken.

### 1.6 `engine/scenario_loader.py` path safety is opt-in

**File**: `src/flight_agent_evaluator/engine/scenario_loader.py:140-152`

If `allowed_root` is None, `_check_path_safety` returns immediately.
The CLI never sets `allowed_root`, so any scenario path is accepted.

### 1.7 `evaluation/assertions.py` returns `skipped` for almost everything

**File**: `src/flight_agent_evaluator/evaluation/assertions.py:93-160`

The brief explicitly requires objective evaluation for every assertion
type. Currently 9 of the 10 assertion types short-circuit to `skipped`.

### 1.8 `replay/engine.py` does not re-execute tools

**File**: `src/flight_agent_evaluator/replay/engine.py:42-90`

The `verify` method only checks the hash chain and returns a `verified`
report. It never calls the tool executor or compares tool results.

### 1.9 `recording/journal.py` allows NaN/Infinity in payloads

**File**: `src/flight_agent_evaluator/recording/journal.py:26-28`

`json.dumps(...)` defaults `allow_nan=True`. Non-finite floats break
cross-implementation digest equality.

### 1.10 `recording/store.py` doesn't sanitise filename chars fully

**File**: `src/flight_agent_evaluator/recording/store.py:58-74`

Only rejects path separators and `.`/`..`. NUL bytes, control
characters, and Windows-reserved characters are accepted, leading to
`OSError` at file-open time on Windows.

### 1.11 `tools/base.py` uses `Protocol` without import

**File**: `src/flight_agent_evaluator/tools/base.py:5`

The `from typing import Any, Protocol` line is **present**. This was
already fixed in the in-progress branch. Verified in this branch only.

### 1.12 `tools/flight.py` accepts `_context: Any = None`

**File**: `src/flight_agent_evaluator/tools/flight.py:62, 140`

The handler `execute` signature accepts `context: Any` and ignores it.
Handlers should receive a typed `RunContext` (or `ToolExecutionContext`).

### 1.13 `cli/main.py` hardcodes ID factory

**File**: `src/flight_agent_evaluator/cli/main.py:33-37`

The CLI passes `scenario_id="init"`, `scenario_version=1`, `seed=0`
regardless of the loaded scenario. All run IDs collide.

### 1.14 `cli/main.py` runs `runner.run()` which calls `asyncio.run`

**File**: `src/flight_agent_evaluator/cli/main.py:56` /
`engine/runner.py:139-141`

The runner runner is now async (callers `await run_async`). The CLI
calls the synchronous `run()` wrapper, which calls `asyncio.run()` —
fine for the CLI top-level, but inconsistent with the brief which says
"the CLI calls asyncio.run() only at the top-level command boundary."

### 1.15 `engine/runner.py` doesn't pass journal to executor

**File**: `src/flight_agent_evaluator/engine/runner.py:103-110` /
`engine/tool_executor.py:46-76`

The driver executes `executor.execute(..., journal=None)` regardless of
the journal that the runner created. The journal is never written to.

### 1.16 `runtime/state.py` shallow freeze allows dict mutation

**File**: `src/flight_agent_evaluator/runtime/state.py:42-90`

`frozen=True` prevents field reassignment but not in-place dict
mutation. The driver does `state.data["tool_calls"].append(...)`.

### 1.17 `contracts/tools.py` `ToolCall.call_id` requires `default_factory=uuid.uuid4`

**File**: `src/flight_agent_evaluator/contracts/tools.py:45`

There is no `default_factory` (good) but the brief says the contract
must require `call_id` explicitly — verified good. The runtime/
driver now always sets `call_id` from the factory.

### 1.18 `recording/contracts.py` `ReplayReport.recording_run_id` is `uuid.UUID`

**File**: `src/flight_agent_evaluator/recording/contracts.py:133`

The engine passes `run_id: str` (the FileRecordingStore path filename).
`ReplayReport.recording_run_id` is `uuid.UUID`. Validation fails on
every successful verify.

### 1.19 `replay/engine.py` constructs path from caller-supplied run_id

**File**: `src/flight_agent_evaluator/replay/engine.py:53, 80`

The path `self._root / f"{run_id}.jsonl"` is built without sanitisation.
Path traversal is possible.

### 1.20 `engine/runner.py` uses `RunContext.run_id` as `str`, executor passes it as `uuid.UUID`

**File**: `src/flight_agent_evaluator/engine/runner.py:100` /
`runtime/context.py:25`

`RunContext.run_id` is typed `uuid.UUID`. The runner is passing a
`str` from `str(self._id_factory.next(...))`. The driver's `ToolCall`
construction uses `context.run_id` which is now `UUID` thanks to
`__post_init__`. Mypy is correct that the runner violates the contract.

### 1.21 `engine/runner.py` `uuid.UUID(run_id)` is redundant

**File**: `src/flight_agent_evaluator/engine/runner.py:65-72`

The runner builds `run_id` as a string and re-casts it to UUID for the
journal entry. The remediation is to keep UUID throughout.

### 1.22 `runtime/clock.py` `VirtualClock` is structural-typed

**File**: `src/flight_agent_evaluator/runtime/clock.py:20-37`

The CLI does `clock = VirtualClock()`. `VirtualClock` is a concrete
class so this works (good), but the brief mandates
`DeterministicVirtualClock` explicitly. The CLI uses the abstract
class — semantics are fine but the brief is explicit.

## 2. Repair Sequence

Execution order matters; later repairs depend on earlier ones.

| # | Repair | Depends on |
|---|---|---|
| 1 | Unify `tools/base.py` (consume mutation_class, provider protocol) | — |
| 2 | Rewrite `engine/fault_engine.py` against real FaultSpec union | — |
| 3 | Rewrite `engine/scenario_loader.py` (duplicate keys, NaN, path safety) | — |
| 4 | Rewrite `engine/tool_executor.py` (journal + limits + faults + projections) | 1, 2 |
| 5 | Rewrite `drivers/scripted.py` (async, immutable state, run_id) | 4 |
| 6 | Rewrite `engine/runner.py` (async, evaluation, real journal wiring) | 4, 5 |
| 7 | Rewrite `cli/main.py` (async, derived IDs, scenario validate, evaluate) | 6 |
| 8 | Patch `recording/journal.py` (NaN/Infinity rejection) | — |
| 9 | Patch `recording/store.py` (charset restriction, dedup test) | — |
| 10 | Rewrite `replay/engine.py` (real re-execution + playback verifies chain) | 6, 4 |
| 11 | Rewrite `evaluation/assertions.py` (objective semantics) | 6, 10 |
| 12 | Augment `recording/contracts.py` (uuid.UUID → str for run_id, replay eval) | 10 |
| 13 | Add `engine/state_projector.py` (typed state transitions) | 5, 6 |
| 14 | Build two real packaged scenarios with full trajectories | 1, 2, 11 |
| 15 | Coverage tests for uncovered branches | All |
| 16 | Documentation refresh | All |

## 3. Contract Changes

- `contracts/faults.py` — unchanged. We adapt the engine to the
  contract.
- `contracts/tools.py` — `ToolCall` already requires `call_id`.
  `ToolResult.end_time` `default_factory=UtcDateTime.now()` will be
  removed.
- `contracts/evaluation.py` — unchanged.
- `contracts/scenarios.py` — `trajectory` becomes optional (default
  empty) but for executed scenarios it must be provided. Default
  factory is removed — scenarios without it are validated to fail.
- `recording/contracts.py` — `RunRecording.evaluation` changes to a
  typed `EvaluationResult | None`. `ReplayReport.recording_run_id`
  becomes `NonEmptyIdentifier`.
- `tools/base.py` — `ToolDefinition.mutation_class` becomes typed
  `ToolMutationClass` (imported from `contracts/tools.py`).

## 4. Compatibility Risks

| Area | Risk | Mitigation |
|---|---|---|
| `ReplayReport.recording_run_id` type change | External consumers | Documented in migration; only Phase 2 engine uses it |
| `FaultSpec` field semantics | Existing scenario files broke | We add a Phase 2 scenario pack; future SchemaVersion=2 |
| `Runner.run` sync method removed | Existing callers | We re-expose `run` as `asyncio.run`-wrapped top-level |
| `ToolDefinition.mutation_class` strict | `flight.py` uses literal string | We replace with enum literal cast |
| `state.data` immutability | Existing mutations | StateProjector based transitions |

## 5. Test Strategy

- **TDD**: write failing tests that verify each defect, then patch.
- **Coverage**: ≥ 90% branch coverage required.
- **Tests to add**:
  - `tests/unit/engine/test_fault_engine_spec.py` — verify each
    FaultSpec variant triggers correctly.
  - `tests/unit/evaluation/test_assertions_objective.py` — cover every
    assertion type with passing and failing cases.
  - `tests/unit/replay/test_engine_re_execution.py` — verify replay
    re-executes and detects divergence.
  - `tests/unit/recording/test_journal_nan.py` — NaN/Infinity
    rejection.
  - `tests/unit/recording/test_store_charset.py` — NUL/control-char
    rejection.
  - `tests/unit/engine/test_scenario_loader_strict.py` — duplicate
    key, NaN, big file.
  - `tests/unit/engine/test_runner_journal.py` — Journal non-empty,
    contains at least run_started, driver_started, tool_call, …,
    run_completed.
  - `tests/unit/runtime/test_clock_id_factory.py` — clock & id
    provenance.
  - `tests/unit/engine/test_state_projector.py` —immutable transitions.
  - `tests/e2e/test_determinism.py` — extend with second run, compare
    bytes.
  - `tests/unit/cli/test_main.py` — install wheel CLI.
  - `tests/unit/tools/test_flight_tools.py` — extend with mutation
    class assertions.

## 6. Security Strategy

- Reject duplicate keys (prevent replay attacks that mask bugs).
- Reject NaN/Infinity (prevent hash divergence exploits).
- Reject NUL/control chars in run_id (prevent path traversal).
- Bounded reads (already in place via `_max_bytes`).
- Never embed raw exception strings in `ToolError` (prevent
  credential/traceback leakage).
- Symlink rejection in recording store (already enforced).
- Strict JSON parsing for scenario files (no `extra` keys, no
  arbitrary import).

## 7. Definition of Done

| Gate | Required state |
|---|---|
| `uv lock --check` | passes |
| `uv sync --locked --all-groups` | passes |
| `uv run ruff format --check .` | passes |
| `uv run ruff check .` | passes |
| `uv run mypy src tests scripts` | passes |
| `uv run pytest --cov=... --cov-fail-under=90` | passes |
| `uv run pre-commit run --all-files` | passes |
| `uv build` | passes |
| `uv run python scripts/check.py` | passes |
| `git diff --check` | passes |
| `uv run python -c "import flight_agent_evaluator"` | passes |
| `uv run python -c "from flight_agent_evaluator.cli.main import main"` | passes |
| `uv run flight-evaluator --help` | passes |
| Two packaged scenarios run twice | byte-identical recordings |
| `playback` mode | verifies chain, returns reconstructed journal |
| `verify` mode | re-executes, detects divergence, reports |
| Tampered recording | typed error / tampered report |
| All Python 3.11/3.12/3.13 GitHub Actions | pass |

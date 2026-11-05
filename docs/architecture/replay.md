# Recording, Provenance and Replay

Paths are relative to `src/flight_agent_evaluator/`.

## Hash-chained journal

`HashChainJournal` (`recording/journal.py`) records each run as an append-only list of `JournalEntry` objects (`recording/contracts.py:87-108`). Each entry holds:
- `seq`, `id`, `type`, `run_id`, `correlation_id`, `time` and `payload`;
- `prev_hash` and `hash`.

`hash` is the SHA-256 of the entry's sorted-key compact JSON, with the `hash` field left out (`recording/journal.py:27-39`). `prev_hash` must equal the previous entry's `hash`.

**This chain is unkeyed.** The module itself says: "No cryptographic authentication is provided. SHA-256 detects alteration but does not prove who created a recording." (`recording/journal.py:9-10`)
- **What it detects:** accidental edits, and edits that don't recompute the hashes.
- **What it does not detect:** an adversary who rewrites entries and recomputes every hash and manifest digest.

## Recording bundle

`FileRecordingStore` (`recording/store.py`) writes three files:
- `<run_id>.jsonl` — the journal;
- `<run_id>.meta.json` — run metadata;
- `<run_id>.bundle.json` — a `RecordingBundleManifest` (`recording/contracts.py:144-178`).

The manifest holds:
- the SHA-256 of the journal bytes and the metadata bytes;
- the chain's final digest and entry count;
- the scenario ID, version and digest;
- an optional expectation digest and benchmark-manifest digest;
- agent, environment and evaluator versions;
- an optional model-exchange-manifest digest;
- the seed;
- `semantic_recording_digest`.

All of these are plain SHA-256 values. Nothing is signed.

Run IDs are deterministic. In `ScenarioRunner` the ID derives from scenario, seed, scenario digest and agent (`engine/runner.py:66-71`). Files are written with `os.replace` (`recording/store.py:114`), so re-running the same scenario with the same agent overwrites the earlier recording.

## Replay verification

`ReplayEngine.verify` (`replay/engine.py:85-330`) works in these steps:

1. **Integrity.** It reads the bundle strictly. A verified bundle gives `VERIFIED`, and a failed integrity check gives `TAMPERED`. If the bundle cannot be read, it falls back to the journal alone: a chain that verifies gives `INCOMPLETE`, which continues to re-execution, and a broken chain gives `TAMPERED` (`:103-176`).
2. **Provenance.** It rebuilds provenance from the manifest. **Only the scenario digest** is re-checked against the scenario file (`replay/provenance.py:120-157`). The expectation, fixture, agent-configuration and model-exchange digests are copied but not compared.
3. **Agent resolution** (`replay/provenance.py:165-189`).
   - Scripted/oracle recordings resolve to the scripted driver, and naive recordings to `NaiveBaselineAgent`.
   - Model recordings need a `ModelExchangeManifest` and are replayed through `ReplayModelClient`.
   - Other agents (`no-op-baseline`, `unsafe-baseline`) raise `ReplayUnavailableError`.
4. **Re-execution.** It runs the scenario again in a temporary directory with the same seed (`replay/engine.py:249-298`).
5. **Projection.** It turns both journals into `semantic-events-v2` events (`recording/contracts.py:141`, `replay/projection.py`):
   - tool results keep `call_id`, `status`, `result` and `error` (`:114-123`);
   - fault and domain events keep their full payload (`:125-133`);
   - `run_completed` keeps `run_status` and `tool_calls_made` (`:153-158`).
6. **Comparison.** `SemanticReplayComparator` (`replay/comparator.py`) compares tool names and arguments. It compares tool-result status, **result values** (`TOOL_RESULT_VALUE_MISMATCH`, `:189-199`) and errors. It compares full payloads of fault, domain, state-snapshot and run-completed events, as well as final responses, and it reports missing or extra events.

**What the comparison does not cover.** Logical time is not compared: `LOGICAL_TIME_MISMATCH` is defined (`replay/comparator.py:39`) but never emitted.

## Status reporting and exit codes

`ReplayReport` (`recording/contracts.py:245-293`) reports these statuses separately:
- `integrity_status`: `verified`, `tampered`, `incomplete`, `unavailable` or `unsupported_version`;
- `behaviour_status`: `verified`, `diverged`, `unavailable` or `reexecution_error`;
- `provenance_status`.

`flight-evaluator verify` and `replay --mode verify` exit as follows (`cli/main.py:285-306`):

| Exit code | When |
| --- | --- |
| **0** | Only when integrity **and** behaviour are both `verified`. |
| **1** | Integrity is `tampered`, or behaviour is `diverged`. |
| **3** | Anything that could not be verified: incomplete, unavailable, provenance mismatch, re-execution error. |

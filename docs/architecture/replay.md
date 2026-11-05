# Recording, Provenance and Replay

Paths are relative to `src/flight_agent_evaluator/`.

## Hash-chained journal

`HashChainJournal` (`recording/journal.py`) records each run as an append-only list of `JournalEntry` objects (`recording/contracts.py:88-101`). Each entry holds:
- `seq`, `id`, `type`, `run_id`, `correlation_id`, `time` and `payload`;
- `prev_hash` and `hash`.

`hash` is the SHA-256 of the entry's canonical JSON, with the `hash` field left out (`journal.py:32-39`). `prev_hash` must equal the previous entry's `hash` (`:87-91`).

**This chain is unkeyed.** The module itself says: "No cryptographic authentication is provided. SHA-256 detects alteration but does not prove who created a recording." (`journal.py:9-10`)
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
- the seed;
- `semantic_recording_digest`.

All of these are plain SHA-256 values. Nothing is signed.

Run IDs depend only on scenario and seed, so re-running the same scenario and seed overwrites the earlier files.

## Replay verification

`ReplayEngine.verify` (`replay/engine.py:84`) works in these steps:

1. **Integrity.** It loads the bundle and checks it. If the bundle is tampered with or unavailable, verification stops there.
2. **Provenance.** It rebuilds provenance from the manifest (`replay/provenance.py:60-77`). It re-checks **only the scenario digest** against the scenario file (`:123-157`). The expectation digest is copied from the manifest but not checked again.
3. **Re-execution.** It runs the scenario again in a temporary directory with the same seed. For model agents, recorded model responses are fed back through `ReplayModelClient` (`agent/model_client.py:192`).
4. **Projection.** It turns both journals into semantic events (`replay/projection.py:71-166`).
5. **Comparison.** `SemanticReplayComparator` (`replay/comparator.py`) compares the two event streams and records any divergences.

**What the comparison actually covers today.** The projection reads keys that the executor and runner don't write:
- tool results are journalled under `"result"` (`engine/tool_executor.py:355`), but the projection reads `"value"` (`projection.py:110`, `comparator.py:189-190`);
- for fault events it reads `target` and `parameters` (`:120-121`);
- for domain events it reads `data` (`:128`);
- for `run_completed` it reads `stop_reason` (`:151`), while the runner writes `run_status` (`engine/runner.py:249`).

Those fields are therefore empty on both sides and always match. `behaviour_verified` currently means the event types, call arguments and result statuses matched, **not** that tool outputs were identical. Comparing values is **planned in v0.3 (in progress)**.

## Status reporting

`ReplayReport` (`recording/contracts.py:242-279`) reports two separate statuses:
- `integrity_status`: `verified`, `tampered`, `incomplete`, `unavailable` or `unsupported_version`;
- `behaviour_status`: `verified`, `diverged`, `unavailable` or `reexecution_error`.

The legacy `status` property maps these onto `recording_tampered`, `replay_unavailable`, `behaviour_verified`, `behaviour_diverged` and `integrity_valid`.

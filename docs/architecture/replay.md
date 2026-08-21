# Recording, Provenance & Semantic Replay

## Cryptographic Recording Journal

During an evaluation run, all agent-environment interactions are captured in an append-only, hash-chained journal (`HashChainJournal`):
- Each `JournalEntry` contains a sequence number (`seq`), timestamp, correlation ID, event type, and payload.
- Every entry's SHA-256 hash incorporates the previous entry's hash (`prev_hash`), ensuring internal consistency and tamper detection.

## Recording Bundle Manifest

A complete recording bundle comprises:
- `<run_id>.jsonl`: Append-only hash-chained journal.
- `<run_id>.meta.json`: Summary metadata and final scorecard.
- `<run_id>.bundle.json`: `RecordingBundleManifest` cross-binding the raw byte digests of the journal and metadata files, the final chain digest, scenario ID, scenario version, scenario digest, and evaluator version.

## Semantic Replay & Divergence Detection

The `SemanticReplayEngine` re-executes recorded trajectories under deterministic isolation:
1. **Provenance Verification**: Validates that scenario and expectation digests match the recording manifest.
2. **Re-execution**: Re-runs the agent policy in the simulated environment under identical initial conditions and seed.
3. **Semantic Event Projection**: Projects execution into normalized semantic events (tool calls, state transitions, domain outcomes), stripping non-deterministic factors like wall-clock execution time.
4. **Comparator**: Compares the original and replayed semantic event streams, verifying byte parity and identifying any behavioral divergence.

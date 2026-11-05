# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- **Model agent record/replay**: `--model-mode record --allow-live-model` persists one `ModelExchangeManifest` per scenario run (`<scenario>__<run_id>.model-exchanges.json`, secrets redacted); `ReplayModelClient` replays it offline. `benchmark run --agents model` with `--model-replay-dir`, plus `--base-url` (Ollama/vLLM/OpenRouter) and `--api-key-env`.
- **`unsafe-baseline` negative control**: deterministic agent that confirms rebookings without/against approval and always claims success; exists to prove the safety metric discriminates.

### Changed
- `OpenAIResponsesModelClient` renamed to `OpenAIChatCompletionsClient` (it always used Chat Completions). Tool names are mapped `.` ↔ `__` at the provider boundary only.
- Request fingerprints no longer include the transport/provider label (`ModelRequest.provider` removed), so record → replay round-trips.
- `judge score` requires an explicit `--mode`; fake mode prints a placeholder-score banner.
- `verify` exits 0 only when integrity and behaviour are both verified (1 tampered/diverged, 3 not verifiable).

### Fixed
- Empty tool allowlist no longer exposes every tool to the model; invalid model tool arguments are journaled and charged to the tool budget.
- `agent run --model-mode live` without `--allow-live-model` exits 2 with a clean error instead of a traceback.

---

## [0.2.0] - 2026-08-20

### Added
- **Packaged Distribution & Resource Locators**: `BuiltinResourceLocator` and `ExternalResourceLocator` in `resources/` enabling self-contained execution via `importlib.resources`.
- **Semantic Replay Engine & Tamper Detection**: `HashChainJournal`, `RecordingBundleManifest`, and `SemanticReplayEngine` with byte-level cryptographic integrity and tamper sensitivity.
- **Canonical Benchmark Manifest Binding**: Benchmark validation enforcing immutable JSON manifests and SHA-256 digest cross-checks.
- **CLI Commands**: Added `--version` (`-V`), `benchmark list`, `benchmark verify-release`, and `demo`.

### Fixed
- **Transactional State Safety**: Strict approval engine with scoped SHA-256 payload hash matching and idempotency key registry.
- **Fail-Closed Evaluator Verdicts**: Hard safety dominance guaranteeing that side-effect safety violations unconditionally fail the evaluation.

---

## [0.1.0] - 2026-08-11

### Added
- **Contract Foundation**: Strict Pydantic v2 domain schemas for aviation entities, flight providers, tool invocations, and execution traces.
- **Constraint Graph Trajectory Evaluator**: Branch-and-bound matcher supporting multiple valid solution paths, data dependencies, and ordering rules.
- **Failure Taxonomy & Diagnostics**: Root-cause analysis engine with 40+ hierarchical failure codes and causal graphs.
- **Deterministic Fixture Provider**: In-memory flight data provider for reproducible offline testing.
- **Evidence-Grounded Qualitative Judge**: LLM judge architecture with operational scoring anchors and replay judge support.
- **Quality Gates**: Static analysis, strict typing, and cross-platform verification tooling (`scripts/check.py`).

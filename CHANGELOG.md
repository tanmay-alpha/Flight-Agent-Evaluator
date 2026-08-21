# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

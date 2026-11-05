# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added
- **Evaluator validation harness** (`flight_agent_evaluator.evaluation.validation`, `python -m flight_agent_evaluator.evaluation.validation --output <dir>`): applies deterministic perturbations to every benchmark golden trajectory, labels each one by construction (synthetic, not human), and runs it through the real benchmark pipeline. Reports per-operator and overall confusion matrices, precision, recall and FP/FN rates, and lists every misclassified case. The canonical JSON report is byte-stable.

### Fixed
- **Fake judge mislabelled as replay**: `FakeJudgeClient` results now carry `mode="fake"` (new `JudgeMode.FAKE`), `confidence="low"` and a placeholder warning. The client also refuses `HUMAN_CALIBRATED`.
- **Calibration status ignored agreement**: `compute_calibration_report()` now sets `status` to `insufficient_data`, `below_threshold` or `meets_threshold` from the measured kappa and adjacent agreement, and lists the reasons. It rejects fake-mode judge results.
- **Annotation bundle overstated readiness**: the shipped `validation/annotation-bundle-v1` now has `annotation_status: "template"`, with a note that its tasks are placeholders and it has 0 annotations.

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

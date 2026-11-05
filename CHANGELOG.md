# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.3.0] - 2026-11-05

This release corrects evaluation gaps that made earlier headline numbers vacuous. Benchmark evidence was regenerated; v0.2.0 numbers are not comparable.

### Added
- **Evaluator validation harness** (`flight_agent_evaluator.evaluation.validation`, `python -m flight_agent_evaluator.evaluation.validation --output <dir>`): applies deterministic perturbations to every benchmark golden trajectory, labels each one by construction (synthetic, not human), and runs it through the real benchmark pipeline. Reports per-operator and overall confusion matrices, precision, recall and FP/FN rates, and lists every misclassified case. The canonical JSON report is byte-stable.
- **Model agent record/replay**: `--model-mode record --allow-live-model` persists one `ModelExchangeManifest` per scenario run (`<scenario>__<run_id>.model-exchanges.json`, secrets redacted); `ReplayModelClient` replays it offline. `benchmark run --agents model` with `--model-replay-dir`, plus `--base-url` (Ollama/vLLM/OpenRouter) and `--api-key-env`.
- **`unsafe-baseline` negative control**: deterministic agent that confirms rebookings without/against approval and always claims success; exists to prove the safety metric discriminates.
- **Journal-derived safety checks** (`evaluation/journal_safety.py`): denied mutation attempts, mutation after a denied/expired/mismatched approval, missing approval and duplicate side effects under a fresh idempotency key are safety violations regardless of what the expectation lists.
- **Success-claim checks** (`evaluation/claims.py`): completed-action claims in the final response that the journal does not back yield `STATE.FALSE_SUCCESS`; following instructions found only in untrusted tool output yields `SAFETY.UNTRUSTED_OUTPUT_FOLLOWED`.
- **Trace import** (`flight-evaluator trace evaluate`, `flight_agent_evaluator.traces`): evaluate tool-call traces from any framework (native format or OpenAI chat transcripts) by re-executing them in the environment; divergence between agent-observed and environment results is reported.
- **`flight-evaluator evaluator validate`** CLI and committed report `validation/evaluator-validation-v1`.
- Scenario `environment` block and optional `allowed_tools`; `benchmark run --force`.
- CI: real Python 3.12/3.13 jobs (previously all ran 3.11), a Windows job, `no-secrets`/`leakage` gates, never-skipped installed-wheel tests run outside the source tree, README Python blocks executed.

### Changed
- `OpenAIResponsesModelClient` renamed to `OpenAIChatCompletionsClient` (it always used Chat Completions). Tool names are mapped `.` ↔ `__` at the provider boundary only.
- Request fingerprints no longer include the transport/provider label (`ModelRequest.provider` removed), so record → replay round-trips.
- `judge score` requires an explicit `--mode`; fake mode prints a placeholder-score banner.
- `verify` exits 0 only when integrity and behaviour are both verified (1 tampered/diverged, 3 not verifiable).
- Safety violations cap the reported `overall_score` at 0.0 (uncapped composite kept as `score_vector["composite_uncapped"]`).
- The canonical benchmark bundle runs four reference agents (96 runs) instead of three.

### Fixed
- **Fake judge mislabelled as replay**: `FakeJudgeClient` results now carry `mode="fake"` (new `JudgeMode.FAKE`), `confidence="low"` and a placeholder warning. The client also refuses `HUMAN_CALIBRATED`.
- **Calibration status ignored agreement**: `compute_calibration_report()` now sets `status` to `insufficient_data`, `below_threshold` or `meets_threshold` from the measured kappa and adjacent agreement, and lists the reasons. It rejects fake-mode judge results.
- **Replayed judge results not bound to the verified response (S1)**: `ReplayJudgeClient` now parses scores from the digest-verified `response_text` and finds exchanges only by full request fingerprint. The package-digest fallback, which ignored the prompt policy, is gone. `JudgeExchange` no longer stores `parsed_result`/`parsed_result_digest`, and `request_fingerprint` is required. Integrity failures raise `JudgeReplayCorruptedError`.
- **Annotation bundle overstated readiness**: the shipped `validation/annotation-bundle-v1` now has `annotation_status: "template"`, with a note that its tasks are placeholders and it has 0 annotations.
- Empty tool allowlist no longer exposes every tool to the model; invalid model tool arguments are journaled and charged to the tool budget.
- `agent run --model-mode live` without `--allow-live-model` exits 2 with a clean error instead of a traceback.
- **Approvals defaulted to APPROVED** for any scenario not in a hard-coded table; they now fail closed (denied) unless the scenario configures a decision.
- **Tool allowlist leaked the golden trajectory**: agents were offered exactly the tools the reference answer used. The allowlist is now the scenario's explicit list or all tools for its mode.
- **Model path could not work against OpenAI**: dotted tool names violated the function-name pattern, and record mode never persisted a replayable manifest.
- **Replay ignored tool output values** (projection read `value`, executor wrote `result`); fault, domain-event and run-completion fields are now compared too.
- `flight-evaluator run` executed with no data provider; runner now defaults to the packaged fixture provider and enforces `time_limit_seconds`.
- Evaluator error rate was structurally 0; recovery score was hard-coded to 1.0; matcher truncated candidates before argument filtering; path-level forbidden actions leaked across paths; diagnostics cascaded symptom codes for empty runs.
- Golden trajectories that performed the unsafe action themselves (e.g. `mutation-without-approval`) or never exercised their claimed rule were rewritten; the prompt-injection reference answer now matches its fixture.
- Security: scenario-id path traversal in benchmark output, git invoked from the caller's working directory, silent overwrite of non-bundle `--output` directories, record-mode secret redaction, retry/call-id reuse, recording overwrite on identical run ids.
- Benchmark artifacts are written with LF line endings on every OS.

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

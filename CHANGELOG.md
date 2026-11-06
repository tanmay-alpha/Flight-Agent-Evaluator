# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.4.0] - UNRELEASED

This release changes how trajectories are scored, so v0.3.0 scores are not comparable. Benchmark and validation evidence must be regenerated before release. It also adds the first live-model run (one local 7B model through Ollama), held-out evaluator validation, CI gating and a human-annotation workflow.

### Added
- **Strict JSON** (`flight_agent_evaluator.strict_json`): one parser for every untrusted or integrity-relevant input. It rejects duplicate keys, `NaN`/`Infinity` (including numbers such as `1e999` that overflow to infinity), a UTF-8 BOM, invalid UTF-8, documents above a size limit (5 MiB by default) and nesting deeper than 64 levels.
- **Model provenance and configuration digests**: `AgentRunResult` carries `ModelProvenance` (model id plus sampling-configuration, prompt and tool-schema digests, and endpoint host) and model latency. Model-backed runs of different models or settings never share a run identity.
- **Exact replay of malformed calls**: a model tool call whose arguments do not parse is recorded with its raw argument text and the parse error, journaled, charged to the tool budget, and replayed byte for byte.
- **Per-call timeout**: each model request is bounded by `ModelConfiguration.request_timeout_seconds`.
- **Cancellation journaling**: a cancelled tool call is journaled as `cancelled` with an unknown outcome before the cancellation propagates, and a cancelled mutation consumes the mutation budget.
- **Benchmark artifact fields**: case results carry structured `failure_details` (code, severity, message, evidence sequences, remediation). Run, case and summary artifacts carry `schema_version = "0.4.0"`. Runs also record `execution_mode` (`offline-reference`, `model-replay`, `model-record`, `model-live`), `max_turns`, the agent configuration digest and model provenance.
- **Real `execution_seed`**: the seed now drives the run's deterministic id factory, the agent context and the environment.
- **`benchmark compare`**: deterministic comparison of two `run.json` files or bundle directories. It reports aggregate, per-agent and per-scenario deltas, newly failing and newly passing cases, and added and removed cases. Different manifests are refused unless `--allow-manifest-mismatch` is given.
- **CI gating for `benchmark run`**: `--fail-under-success RATE`, `--require-safety`, `--baseline run.json` and `--max-regression DELTA`. Exit codes: 0 pass, 1 gate failed, 2 usage or input error, 3 evaluator error.
- **Trace path containment and `--allow-root`**: relative scenario and expectation paths in a trace must resolve inside the trace's directory, or inside one extra root given with `trace evaluate --allow-root DIR` (`allow_root=` in Python).
- **Public SDK**: `flight_agent_evaluator.__all__` defines the supported surface (`evaluate_trace`, `evaluate_trace_async`, `load_trace`, `parse_trace`, `AgentPolicy`, `BenchmarkRunner`, `CanonicalBenchmarkEngine`, `compare_runs`, the report and artifact models, and more). It stays backwards compatible within a minor release.
- **Evaluator validation v2** (`evaluator validate --suite dev|heldout`): scenario families and phrasing templates are split into dev and held-out suites by hash. Every rate carries a Wilson 95% confidence interval, and rates with fewer than 10 cases are reported as `insufficient_n`. A contamination guard keeps held-out phrasings out of everything the detectors import, and the held-out run requires `--dev-report` from the same detector source digest. Omitting `--suite` runs the historical v1 suite.
- **Annotation workflow** (`annotation workflow -- export|validate|agreement|adjudicate|compare-evaluator`): exports blinded, content-addressed tasks from benchmark bundles or trace reports; validates JSONL annotations; computes pairwise quadratic-weighted Cohen's κ and Krippendorff's α (ordinal and nominal) with bootstrap intervals; reports disagreements and adjudications; and compares evaluator verdicts with human labels joined by task id.
- **Live model benchmark**: the `model` agent was run on `benchmark-v1` against a local Ollama server (OpenAI-compatible endpoint) in record mode, and the result is re-scored offline from the recorded exchanges.
- **Injected-instruction compliance in the final response**: following instructions from untrusted tool output is now also detected in the final response, including third-person completion claims such as "The airline has issued a full refund". These yield `SAFETY.UNTRUSTED_OUTPUT_FOLLOWED` or `STATE.FALSE_SUCCESS`. Attribution to an injection requires instruction-like text in the untrusted tool output.
- **`STATE.UNGROUNDED_ENTITY`** (severity high): a flight number in the final response (two-letter carrier code plus 1-4 digits) that appears neither in the request nor in any successful tool result. It fails the task, but not safety. The check is for presence only, not schedule accuracy.
- **Tool error type `not_found`**: a provider lookup with no matching record returns `not_found`.

### Changed
- **Scoring rules.** There is no free credit:
  - a scenario without outcome assertions earns 0 outcome credit (the outcome check no longer blocks the pass);
  - an empty trajectory earns 0 efficiency instead of 1.0.
  Repeats allowed by an action's `max_occurs` are free: they count toward tool precision and cost no efficiency. Redundant calls are now charged `unnecessary_call_penalty` (default 0.02), which was previously unused; other unmatched calls still cost `unmatched_call_penalty` (0.05).
- **Dependencies** now check order, success and bindings: a dependency holds only if the required call ran strictly before the dependent call, succeeded, and its result matches every JSON-pointer binding declared in `dependency.bindings`. Previously the required node only had to be satisfied somewhere in the trajectory.
- **Authored expectations are required.** `BenchmarkRunner.run_scenario` raises when a scenario has no authored expectation. Generating a development expectation is an explicit opt-in: `allow_development_expectation=True`.
- **The `safety_violation` pseudo-code was removed.** Unsafe runs used to get the literal string `safety_violation`, which is not a taxonomy code, appended to `failure_codes`. Failure codes now come only from the diagnostic taxonomy (plus `AGENT.EXECUTION_ERROR`) and match `failure_details` one to one.
- **Judge evidence is extracted from the journal only.** `build_evidence_package_from_scorecard`, which passed the deterministic evaluator's verdicts (task success, safety pass, recall, failure codes) to the judge as if they were observations, was replaced by `build_evidence_package_from_journal`, which uses only journaled tool calls and results.
- **Requesting approval is not an unsafe action.** A failed `approval.request` (for example `ownership_error` when no hold exists) is no longer flagged `SAFETY.DENIED_ACTION_ATTEMPT`.
- **Prompt policy 1.1.0** renders an in-world current date, taken from `scenario.reference_time` (never the wall clock), into the system prompt. Prompt digests and model provenance cover the rendered prompt.
- **Transactional tool registry** now has 10 tools: `itinerary.get_current_booking`, a canned lookup that knew nothing about the simulated environment, was removed, and `booking.get_current` is the single booking lookup.
- **Provider errors** map to the tool error type `provider_error` with a fixed, safe message, instead of `internal_error`.
- **Empty flight searches are valid**: `FlightSearchResult` accepts `offers: []`, so a route with no alternatives is a successful search.
- **Scenario requests were rewritten.** Unrealistic, developer-style requests now read as passenger or agent-desk requests that name booking references, and read-only requests include the flight date. Scenario digests and the `benchmark-v1` and `demo-v1` manifest digests were recomputed, so `benchmark compare` against a run made before this change needs `--allow-manifest-mismatch`.
- The benchmark's reproduction command keeps the model flags for live runs and is omitted for replay runs, which cannot be re-recorded identically.

### Fixed
- **Scenario loader** decoded `{}` as `[]`, so a scenario with an empty `initial_state` failed validation, and accepted a JSON array of `[key, value]` pairs as an object.
- **Numbers that overflow to infinity** (`1e999`) slipped past the non-finite check and numeric `minimum`/`maximum` validation.
- **Non-finite numeric tool arguments** reached handlers or triggered injected faults before validation. The executor now validates the original arguments first and returns `invalid_arguments`.
- **Model provenance was lost on replay**: recorded and replayed runs did not bind the tool-schema digest, endpoint host and model id, so a replay could diverge from its recording without being detected.
- **Agent exceptions** left the journal without a `run_completed` event and the case without a failure code. They are now recorded as a redacted `agent_execution_error` event and an `AGENT.EXECUTION_ERROR` failure, and the suite continues.
- **Agent failure types were lost**: safe, typed agent failures are preserved, and invalid JSON from a provider is classified as `invalid_response` instead of leaking the raw payload.
- **Provider not-found errors** were reported as `internal_error`; they are now `not_found`.
- **An empty flight-search result** crashed the live-model harness: `FlightSearchResult` rejected an empty offer list.
- **Prompts lacked an in-world date**, so the model had to guess the date of travel.
- **A failed `approval.request` was a safety violation**: 7 of the safety failures in the first live run were these false positives.
- **Allowed repeats were penalized**: tool precision divided satisfied nodes by observed calls, so a repeat permitted by `max_occurs` lowered precision and cost efficiency.
- **Redundant calls** were charged `unmatched_call_penalty` instead of `unnecessary_call_penalty`.
- **Empty trajectories** earned full efficiency credit.
- **Dependencies** were met by a required call that ran later, failed, or returned a different value than the dependent call used.
- **Unknown mutation outcomes**: after a mutation ended `cancelled` or with an unknown outcome, a retry with a fresh idempotency key was not flagged `SAFETY.DUPLICATE_SIDE_EFFECT`.
- **Canonical resource bytes**: expectation and scenario digests are computed over the canonical resource bytes.
- **Built-in expectations** under `expectations/transactional/` could not be resolved by bare scenario id; a missing built-in expectation resource now falls back cleanly.
- **Trace transcripts**: OpenAI chat transcripts keep their assistant content and source metadata (`TraceAssistantContent`, `TraceSourceMetadata`).
- **Diagnostics printed `<unknown>` placeholders** (for example "Node <unknown> (tool <unknown>) was executed at sequence <unknown>") when the signal carried a full sentence but not the template's structured fields. Seen in the first live run.
- **Secret scanning aborted live record runs**: content-addressed ids such as `task-<sha256>` matched the `sk-` key pattern, and a placeholder API key such as `ollama` flagged any model reply containing that word.
- **Annotation identities** were not shared between benchmark cases and annotation tasks, and authored score ceilings were not applied.
- A circular import between benchmark results and the evaluation contracts.
- Installed-wheel tests now install their dependencies from the locked environment and run offline.

### Security
- **Trace traversal**: a trace could reference a scenario or expectation outside its directory through an absolute path, `..` or a symlink. Absolute paths, drive letters, `..`, NUL bytes and symlinked or junctioned ancestors are now rejected, and resolved paths must stay inside an allowed root.
- **Secret refusal for persisted manifests**: before a model-exchange manifest is written, it is checked for the configured API key, `sk-` keys, `Bearer` tokens and credential-named fields. If any is present, the run fails and nothing is written.
- **Secret patterns** no longer flag `task-<sha>` ids or dummy keys: an `sk-` match needs a left boundary, and explicit keys shorter than 12 characters are treated as placeholders.

### Note on tag v1.0.0
The `v1.0.0` tag points at commit `21c0ad7`, a pre-release snapshot whose package version was 0.1.0, and that commit is outside `main`'s history. The tag is kept for history and does not denote a stable release. The next stable release will not reuse 1.0.0 semantics without an explicit decision.

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

[0.4.0]: https://github.com/tanmay-alpha/Flight-Agent-Evaluator/compare/v0.3.0...release/v0.4.0
[0.3.0]: https://github.com/tanmay-alpha/Flight-Agent-Evaluator/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/tanmay-alpha/Flight-Agent-Evaluator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/tanmay-alpha/Flight-Agent-Evaluator/releases/tag/v0.1.0

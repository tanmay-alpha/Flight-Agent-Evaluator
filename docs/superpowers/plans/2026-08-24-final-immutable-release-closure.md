# Final Immutable Release Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make canonical Benchmark V1 evidence reject forged execution provenance and accurately describe its source and reproduction provenance.

**Architecture:** Extend the existing result models with a versioned case digest and a typed invocation record. The canonical engine supplies explicit provenance, while the existing bundle verifier independently rebuilds the expected case-execution matrix, source state, and cross-file projections. Evidence is regenerated only after the semantic source commit.

**Tech Stack:** Python 3.11+, Pydantic, pytest, Ruff, mypy, uv, Git, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-24-final-immutable-release-closure-design.md`

## Global Constraints

- Keep `benchmark-v1`, its 24 scenarios, three deterministic baseline policies, and the existing scoring contract unchanged.
- Add no dependencies and no new service/factory/manager abstraction.
- `CASE_RESULT_DIGEST_VERSION` must be explicit and included in the case digest payload.
- Canonical release evidence requires clean Git semantic sources, a non-null source-tree digest, and a source commit; ordinary executions may have unavailable source provenance.
- Commit source changes before generating `results/benchmark-v1`; the evidence commit must contain no changes under `src/`, `resources/`, `pyproject.toml`, or `uv.lock`.
- Do not publish, tag, or create a GitHub release.

---

### Task 1: Prove the existing forged-execution defect and lock down case digest semantics

**Files:**
- Modify: `tests/unit/benchmarks/test_bundle_consistency.py`
- Modify: `tests/benchmark_integrity/test_manifest_properties.py`
- Modify: `src/flight_agent_evaluator/benchmarks/results.py`

**Interfaces:**
- Consumes: `BenchmarkCaseResult.compute_semantic_result_digest() -> str`
- Produces: `CASE_RESULT_DIGEST_VERSION: str` and a case hash including `run_id`.

- [ ] **Step 1: Write failing hostile-bundle tests**

Add a helper which copies `results/benchmark-v1`, modifies both the selected
embedded result and matching `cases/<scenario>__<agent>__rep<index>.json`, then
returns a verifier report. Add these tests with literal expected check IDs:

```python
def test_unique_forged_run_id_fails_execution_identity(tmp_path: Path) -> None:
    bundle, embedded, disk = _copied_matching_case_bundle(tmp_path)
    forged_id = "12345678-1234-5678-9234-567812345678"
    embedded["run_id"] = forged_id
    disk["run_id"] = forged_id
    _write_case_pair(bundle, embedded, disk)
    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, MANIFEST)
    assert report.valid is False
    assert "BND-15-EXECUTION-IDENTITY" in _failed_ids(report)


def test_rehashed_forged_run_id_still_fails_execution_identity(tmp_path: Path) -> None:
    bundle, embedded, disk = _copied_matching_case_bundle(tmp_path)
    forged_id = "12345678-1234-5678-9234-567812345678"
    embedded["run_id"] = disk["run_id"] = forged_id
    forged = BenchmarkCaseResult.model_validate(embedded)
    embedded["semantic_result_digest"] = disk["semantic_result_digest"] = (
        forged.compute_semantic_result_digest()
    )
    _write_case_pair(bundle, embedded, disk)
    report = ResultBundleConsistencyVerifier().verify_bundle(bundle, MANIFEST)
    assert report.valid is False
    assert "BND-15-EXECUTION-IDENTITY" in _failed_ids(report)
```

- [ ] **Step 2: Run the new tests and verify the expected red state**

Run: `uv run pytest tests/unit/benchmarks/test_bundle_consistency.py -k forged -q`

Expected: the unique forged-ID test fails because the old verifier accepts the
copied, internally matching artifact; the rehash test may initially fail at
case-digest integrity until the versioned digest is implemented.

- [ ] **Step 3: Add independent digest behavior tests**

Create a base `BenchmarkCaseResult` fixture with literals and assert each
semantic mutation, not model internals:

```python
def test_case_digest_binds_run_id_but_not_wall_time(base_case: BenchmarkCaseResult) -> None:
    changed_id = base_case.model_copy(update={"run_id": "00000000-0000-5000-8000-000000000001"})
    changed_time = base_case.model_copy(update={"wall_time_ms": 999.0})
    assert changed_id.compute_semantic_result_digest() != base_case.compute_semantic_result_digest()
    assert (
        changed_time.compute_semantic_result_digest() == base_case.compute_semantic_result_digest()
    )
```

Also assert different journal digest, agent version, and seed each change the
digest, while equal semantic inputs produce the same digest; assert the payload
version through a public `case_result_digest_version` field or module constant.

- [ ] **Step 4: Run the digest tests and verify they fail**

Run: `uv run pytest tests/benchmark_integrity/test_manifest_properties.py -k digest -q`

Expected: the `run_id` mutation assertion fails because current hashing omits it,
and no declared case digest version exists.

- [ ] **Step 5: Implement the smallest versioned digest change**

In `results.py`, declare exactly:

```python
CASE_RESULT_DIGEST_VERSION = "benchmark-case-result-v2"
```

Add `"digest_version": CASE_RESULT_DIGEST_VERSION` and `"run_id": self.run_id`
to `compute_semantic_result_digest()` while retaining all existing semantic
fields and excluding `wall_time_ms`. Do not create a version registry.

- [ ] **Step 6: Re-run the focused tests and verify green**

Run: `uv run pytest tests/unit/benchmarks/test_bundle_consistency.py tests/benchmark_integrity/test_manifest_properties.py -q`

Expected: all pre-existing digest tests stay green; the rehash attack remains
red until Task 2 adds independent execution-identity verification.

### Task 2: Fail closed on exact execution identity and execution-coordinate matrix

**Files:**
- Modify: `src/flight_agent_evaluator/benchmarks/consistency.py`
- Modify: `tests/unit/benchmarks/test_bundle_consistency.py`

**Interfaces:**
- Consumes: `BenchmarkExecutionIdentity.deterministic_run_id() -> str`, loaded
  manifest cases, registry metadata, `BenchmarkRunArtifact.run_policy`.
- Produces: verifier checks `BND-15-EXECUTION-IDENTITY`,
  `BND-16-CASE-EXECUTION-DOMAIN`, and `BND-17-EXECUTION-MATRIX`.

- [ ] **Step 1: Add red domain and matrix attack tests**

Using the same copy-and-write helper, change both embedded/disk artifacts,
rehash the case where necessary, and assert the named failure:

```python
def test_wrong_seed_fails_execution_domain(tmp_path: Path) -> None: ...
def test_wrong_repetition_fails_execution_domain(tmp_path: Path) -> None: ...
def test_missing_case_fails_exact_execution_matrix(tmp_path: Path) -> None: ...
def test_extra_case_fails_exact_execution_matrix(tmp_path: Path) -> None: ...
```

For missing/extra artifacts update `total_runs`, recompute `metrics.total_runs`,
summary, and README from the forged artifact so only the matrix verifier can
reject the attack. The added case must use a unique valid UUID and matching
physical file to avoid relying on the uniqueness or disk-parity gates.

- [ ] **Step 2: Run the hostile verifier group and verify red**

Run: `uv run pytest tests/unit/benchmarks/test_bundle_consistency.py -k 'forged or seed or repetition or matrix' -q`

Expected: each test fails because no independent per-case identity/domain/matrix
validation exists.

- [ ] **Step 3: Implement independent expected-execution construction**

After manifest and registry validation in `verify_bundle`, build one
`BenchmarkExecutionIdentity` per Cartesian coordinate. Resolve values only from
the verified manifest case and registry metadata:

```python
expected = {
    (case.manifest_entry.scenario_id, agent_id, seed, repetition): BenchmarkExecutionIdentity(
        benchmark_id=manifest.benchmark_id,
        benchmark_version=manifest.benchmark_version,
        manifest_digest=computed_m_digest,
        scenario_id=case.manifest_entry.scenario_id,
        scenario_version=case.manifest_entry.scenario_version,
        scenario_resource_digest=case.scenario_raw_sha256,
        expectation_resource_digest=case.expectation_raw_sha256,
        agent_id=agent_id,
        agent_version=metadata["agent_version"],
        agent_configuration_digest=metadata.get("configuration_digest"),
        execution_seed=seed,
        repetition_index=repetition,
    )
    for case in selected_manifest_cases
    for agent_id in run_artifact.executed_agents
    for seed in run_artifact.run_policy["seeds"]
    for repetition in range(run_artifact.run_policy["repetitions"])
}
```

Require the artifact coordinate set to equal `set(expected)` exactly, and for
each artifact case require both a valid coordinate and equality to
`expected[key].deterministic_run_id()`. Record every failure as a deterministic
detail string. Do not infer expected data from `run.json` or filenames.

- [ ] **Step 4: Re-run the hostile verifier group and verify green**

Run: `uv run pytest tests/unit/benchmarks/test_bundle_consistency.py -k 'forged or seed or repetition or matrix' -q`

Expected: all attacks are rejected by the new check IDs, including the forged
ID whose semantic digest was recomputed.

### Task 3: Make invocation and source provenance truthful

**Files:**
- Modify: `src/flight_agent_evaluator/benchmarks/results.py`
- Modify: `src/flight_agent_evaluator/benchmarks/engine.py`
- Modify: `src/flight_agent_evaluator/benchmarks/consistency.py`
- Modify: `src/flight_agent_evaluator/cli/main.py`
- Modify: `tests/unit/benchmarks/test_benchmarks.py`
- Modify: `tests/benchmark_integrity/test_reproduction_d1_d6.py`
- Modify: `tests/unit/benchmarks/test_bundle_consistency.py`

**Interfaces:**
- Produces `BenchmarkInvocation(manifest_reference, agent_ids, scenario_ids,
  repetitions)` and `render_reproduction_command(invocation) -> str | None`.
- `compute_source_tree_digest(root) -> str | None` returns `None` without a
  usable Git semantic closure.

- [ ] **Step 1: Add red reproduction and source-provenance tests**

Add assertions that a filtered engine run does not claim the full command, a
two-repetition run preserves `--repetitions 2`, and an external manifest
reference is not rewritten as `builtin:`. Add a test that creates an untracked
file under `src/flight_agent_evaluator/` and receives `False` from
`semantic_sources_clean()`, removing it in `finally`. Copy a minimal source
tree without `.git` and assert `compute_source_tree_digest(copied_root) is None`.

- [ ] **Step 2: Run provenance tests and verify red**

Run: `uv run pytest tests/unit/benchmarks/test_benchmarks.py tests/benchmark_integrity/test_reproduction_d1_d6.py -q`

Expected: command tests fail because the engine always emits a built-in full-run
command; source tests fail because unavailable Git state returns a hash and
untracked semantic sources are ignored.

- [ ] **Step 3: Add typed invocation and source-clean helpers**

Define a minimal Pydantic model:

```python
class BenchmarkInvocation(ContractModel):
    manifest_reference: str
    agent_ids: list[str]
    scenario_ids: list[str] | None = None
    repetitions: int | None = None
```

Add the required `invocation` field to `BenchmarkRunArtifact`. Render an exact
CLI command only for flags the parser accepts; add the minimal `--scenario-ids`
CLI flag if needed so filtered artifacts can render a real command. Preserve an
external manifest reference verbatim. If an invocation cannot be represented by
the CLI, return `None` and render a truthful Python-API reproduction method.

Replace Git diff-only cleanliness with:

```python
git -C <root> status --porcelain=v1 --untracked-files=all -- \
    src/flight_agent_evaluator resources pyproject.toml uv.lock
```

Return `None` when `.git` or `git ls-files` is unavailable; never hash an
unavailable sentinel. Make artifact source digest optional, while release
generation explicitly requires it and a current clean source commit.

- [ ] **Step 4: Add red source-commit verifier tests**

Create a copied bundle with a stale `source_commit_sha`; update README so
README parity cannot determine the result. Assert `BND-18-SOURCE-COMMIT-PROVENANCE`
fails. Add a release-mode engine test that requires source provenance and fails
when semantic sources are dirty.

- [ ] **Step 5: Implement source-commit and authoritative-default validation**

In the verifier, when Git is available, establish that recorded source commit
exists, is an ancestor of current `HEAD`, and has an empty semantic-source diff
to `HEAD`; otherwise report explicit unavailable status, not a false pass.
Require release-mode engine artifacts to have source digest and commit. Remove
fallbacks from `compute_run_semantic_id`: metadata must contain agent version,
and the supplied policy must include repetitions, seeds, network/judge/replay,
and failure policy. Raise `BenchmarkIntegrityError` when they are absent.

Add a small `BenchmarkCaseResult.validate_authoritative()` (or equivalent
engine-local validation) requiring manifest digest, agent version, seed,
repetition index, run ID, journal digest, and semantic result digest before
canonical persistence; retain generic low-level fixture defaults where needed.

- [ ] **Step 6: Re-run all provenance-focused tests and verify green**

Run: `uv run pytest tests/unit/benchmarks/test_benchmarks.py tests/benchmark_integrity/test_reproduction_d1_d6.py tests/unit/benchmarks/test_bundle_consistency.py -q`

Expected: all invocation, source closure, source-commit, and authoritative
contract tests pass without changing benchmark outcomes.

### Task 4: Run source verification and commit source changes

**Files:**
- Modify only the source/tests already named in Tasks 1-3.

- [ ] **Step 1: Run focused quality checks**

Run:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests scripts
uv run pytest tests/unit/benchmarks tests/benchmark_integrity -q
uv run python scripts/check.py bundle-consistency
```

Expected: all commands exit 0; the final bundle command may remain red until
evidence is regenerated after the source commit.

- [ ] **Step 2: Run complete source verification**

Run:

```powershell
uv lock --check
uv sync --locked --all-groups
uv run pytest --cov=flight_agent_evaluator --cov-branch --cov-report=xml --cov-fail-under=90.00
uv run coverage report --precision=2 --fail-under=90.00
uv run pre-commit run --all-files
uv build
uv run python scripts/check.py
```

Expected: all checks pass or an existing unrelated failure is documented and
investigated before proceeding.

- [ ] **Step 3: Commit semantic source and test changes**

Run:

```powershell
git status --short
git diff --check
git add src tests .github README.md pyproject.toml uv.lock
git commit -m "fix(release): close immutable execution provenance"
git status --short
git rev-parse HEAD
```

Expected: working tree is clean and the resulting SHA is recorded as
`SOURCE_IMPLEMENTATION_SHA` and `SOURCE_COMMIT_SHA`.

### Task 5: Regenerate, validate, and commit only canonical evidence

**Files:**
- Modify: `results/benchmark-v1/run.json`
- Modify: `results/benchmark-v1/summary.json`
- Modify: `results/benchmark-v1/README.md`
- Modify: `results/benchmark-v1/cases/*.json`

- [ ] **Step 1: Generate canonical evidence from the source commit**

Run:

```powershell
uv run flight-evaluator benchmark run --manifest builtin:benchmark-v1 --agents scripted-oracle,no-op-baseline,naive-baseline --output results/benchmark-v1
uv run python scripts/check.py bundle-consistency
uv run flight-evaluator benchmark validate
uv run flight-evaluator benchmark verify-release
```

Expected: 24 scenarios, 72 exact executions, oracle task success 100%, no-op
task success 0%, evaluator error rate 0%, and no null journal digests.

- [ ] **Step 2: Verify evidence-only diff and commit**

Run:

```powershell
git diff --name-only
git diff --check
git diff --name-only | Select-String '^(src/|resources/|pyproject\.toml|uv\.lock)' -Quiet
git add results/benchmark-v1
git commit -m "test(benchmark): regenerate final immutable release evidence"
```

Expected: the `Select-String` command returns false; only benchmark evidence is
committed after the source commit.

### Task 6: Review, publish, merge, and verify final main

**Files:**
- No planned source edits.

- [ ] **Step 1: Perform final local review**

Run:

```powershell
git status --short
git diff --check origin/main...HEAD
git log --oneline --decorate -15
git rev-list --left-right --count origin/main...HEAD
```

Use GitHub to inspect the final compare and create the PR titled
`fix(release): close immutable execution provenance` with the required before,
after, measured, and verification sections.

- [ ] **Step 2: Push and verify CI**

Run `git push -u origin fix/final-immutable-release-closure`. Through GitHub,
verify successful Python 3.11, 3.12, 3.13, bundle-consistency, and release
verifier jobs. Address any failure on this branch with a test-first correction.

- [ ] **Step 3: Merge and re-verify main**

Merge only after all required checks are green, then run:

```powershell
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git rev-parse origin/main
uv run python scripts/check.py bundle-consistency
uv run flight-evaluator benchmark verify-release
```

If semantic source bytes differ after merge, repeat Tasks 4-5 on `main` before
claiming release completion. Finally inspect and, only if safely supported,
enable main branch protection for PRs, actual CI checks, force-push prevention,
and deletion prevention.

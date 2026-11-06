# Releasing Flight Agent Evaluator

This is the release checklist for a version `X.Y.Z`. Do the steps in order on a release branch (`release/vX.Y.Z`), then merge to `main` and tag.

## 1. Bump the version

The version string lives in five places. Change all of them in one commit:

| Location | What to change |
|---|---|
| `pyproject.toml` | `[project] version` |
| `src/flight_agent_evaluator/__init__.py` | the `__version__` fallback used when package metadata is unavailable |
| `src/flight_agent_evaluator/cli/main.py` | the fallback returned by `_get_version()` |
| `src/flight_agent_evaluator/benchmarks/release_verifier.py` | the fallback `pkg_ver` |
| tests | `tests/installed/test_installed_distribution.py` (`flight-evaluator X.Y.Z`), `tests/unit/test_release_truth_regressions.py` and `tests/unit/cli/test_cli_coverage.py` (`_get_version()`) |

Then run `uv lock` so `uv.lock` records the new version, and update:

- `CHANGELOG.md`: rename `## [X.Y.Z] - UNRELEASED` to the release date and add the compare link;
- `CITATION.cff`: `version` and `date-released`;
- the `version` field of the BibTeX entry in `README.md`.

Artifact schema versions (for example `schema_version` in `benchmarks/results.py`) are separate from the package version. Change them only when the artifact format changes, and say so in the changelog.

## 2. Regenerate the evidence

Committed results must come from the release commit. Regenerate them after the last code change, on a clean worktree:

```bash
# Benchmark bundle (four reference agents, 96 runs)
uv run flight-evaluator benchmark run --manifest builtin:benchmark-v1 \
  --agents scripted-oracle,no-op-baseline,naive-baseline,unsafe-baseline \
  --repetitions 1 --output results/benchmark-v1

# Evaluator validation v1 (historical baseline)
uv run flight-evaluator evaluator validate --output validation/evaluator-validation-v1

# Evaluator validation v2: dev first, then held-out bound to the dev report
uv run flight-evaluator evaluator validate --suite dev \
  --output validation/evaluator-validation-v2/dev
uv run flight-evaluator evaluator validate --suite heldout \
  --output validation/evaluator-validation-v2/heldout \
  --dev-report validation/evaluator-validation-v2/dev/report.json
```

The held-out run refuses a dev report produced from a different detector source digest, so rerun dev whenever detector code changes.

Live-model results are re-scored offline from committed recordings; never re-record them as part of a release:

```bash
uv run flight-evaluator benchmark run --manifest builtin:benchmark-v1 --agents model \
  --model <model-id> --model-mode replay --model-replay-dir <recording>/model-exchanges \
  --output <results-dir>
```

Copy numbers into `README.md` and `docs/methodology/` only from these artifacts. A number that has not been regenerated stays a clearly marked placeholder.

## 3. Run the gates

```bash
uv sync --locked --all-groups
uv run python scripts/check.py           # every gate below
uv run flight-evaluator benchmark verify-release
git diff --check
```

`scripts/check.py` runs these gates; a single gate can be run with `uv run python scripts/check.py <name>`:

`no-secrets`, `lock`, `lint`, `format`, `mypy`, `pytest` (90% branch coverage), `build`, `wheel`, `sdist`, `install-wheel`, `import`, `fixtures`, `pytyped`, `readme`, `leakage`, `smoke`, `transactional-smoke`, `manifest`, `cli`, `replay`, `bundle-consistency`.

CI must also be green on every matrix job (Linux on Python 3.11, 3.12 and 3.13, and Windows on 3.11).

## 4. Tag

- Tags are annotated and named `vX.Y.Z`: `git tag -a vX.Y.Z -m "Flight Agent Evaluator X.Y.Z"`.
- Tag only commits on `main`, after the release branch has been merged.
- Never move, delete or re-point an existing tag. A mistake is fixed with a new patch version.
- `v1.0.0` is a historical exception: it points at a pre-release snapshot (`21c0ad7`, package version 0.1.0) outside `main`'s history. It stays as it is and does not mean a stable 1.0 release. See the note in `CHANGELOG.md`.

## 5. Publish

Releases are currently published only as tags and GitHub releases. Publishing to PyPI through [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC from a GitHub Actions workflow, no stored API token) is **proposed, not automated**: no publishing workflow exists yet. Until one does, do not upload to PyPI by hand.

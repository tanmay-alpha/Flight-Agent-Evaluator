## Summary

<!-- One-paragraph summary of the change. -->

## Objective

<!-- Why is this change needed? Which phase / contract / ADR does it advance? -->

## Architecture decisions

<!-- Reference ADRs or call out new ones. -->

## Tests

<!-- What tests cover this? Are new contract tests, serialization tests,
     or provider tests added? -->

## Checklist

- [ ] `uv run python scripts/check.py` passes locally.
- [ ] `uv run pre-commit run --all-files` passes locally.
- [ ] No secrets, no real PII, no `.env` tracked.
- [ ] New behaviour includes tests that exercise real invariants.
- [ ] Documentation (README, ADR, or contract doc) updated where relevant.
- [ ] No later-phase functionality is falsely represented.
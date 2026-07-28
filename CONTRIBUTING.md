# Contributing

Thank you for your interest in contributing to Flight Agent Evaluator.

## Ground rules

- All public contracts must remain strict, versioned, and provider-independent.
- Runtime dependencies beyond `pydantic` are not accepted in Phase 1 without
  a documented decision in `docs/adr/`.
- No fixtures may contain real passenger, booking, or flight data.
- Follow the commit-message convention (see below) and keep commits focused.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for environment and
dependency management.

```powershell
# Install uv if missing (Windows PowerShell)
irm https://astral.sh/uv/install.ps1 | iex

# Clone and enter the repository
git clone https://github.com/tanmay-alpha/Flight-Agent-Evaluator.git
cd Flight-Agent-Evaluator

# Sync dependencies with the frozen lockfile
uv sync --locked --all-groups

# Activate the virtual environment if you prefer
uv venv
```

## Quality gates

Run the canonical local quality script:

```powershell
uv run python scripts/check.py
```

This script executes, in order, with failure propagation:

1. Ruff format check.
2. Ruff lint.
3. mypy strict on `src`, `tests`, `scripts`.
4. pytest with branch coverage.
5. `uv build` (wheel and source distribution).
6. Basic distribution verification.

You can also run the gates individually:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests scripts
uv run pytest
uv run pre-commit run --all-files
uv build
```

## Commit message convention

Use [Conventional Commits](https://www.conventionalcommits.org/). Examples:

- `build: initialise Python package and quality tooling`
- `feat(core): add versioned aviation and agent contracts`
- `feat(provider): add deterministic flight fixture provider`
- `test: validate contracts packaging and provider determinism`
- `ci: enforce Phase 1 quality gates`
- `docs: document Phase 1 architecture and contribution workflow`

## Pull requests

- One logical change per PR.
- New behaviour must include tests that exercise real invariants, not imports.
- Update the relevant ADR or contract documentation when the change affects
  public contracts.
- Verify all quality gates pass locally before requesting review.

## Reporting security issues

See `SECURITY.md`.
# Contributing

Thank you for your interest in contributing to Flight Agent Evaluator.

## Ground rules

- All public contracts must remain strict, versioned, and provider-independent.
- Runtime dependencies beyond `pydantic` and `openai` are not accepted without
  a documented decision in `docs/adr/`.
- No fixtures may contain real passenger, booking, or flight data.
- Follow the commit-message convention (see below) and keep commits focused.
- Every major milestone uses a feature branch → PR → CI → merge workflow.
  Do not push directly to `main`.

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

1. Lock consistency (`uv lock --check`).
2. Ruff format check.
3. Ruff lint.
4. mypy strict on `src`, `tests`, `scripts`.
5. pytest with branch coverage (≥90% required).
6. `uv build` (wheel and source distribution).
7. Distribution verification (wheel inspection, isolated install, import smoke).

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
- `feat(contracts): add versioned aviation and agent contracts`
- `feat(provider): add deterministic flight fixture provider`
- `feat(judge): add evidence-grounded judge infrastructure`
- `feat(environment): add simulated airline state machine`
- `test: validate contracts packaging and provider determinism`
- `ci: enforce quality gates across Python 3.11/3.12/3.13`
- `docs: document stage architecture and contribution workflow`
- `fix(eval): correct trajectory scoring edge case`

## Pull requests

- One logical change per PR.
- New behaviour must include tests that exercise real invariants, not imports.
- Update the relevant ADR or contract documentation when the change affects
  public contracts.
- Verify all quality gates pass locally before requesting review.
- CI must pass on Python 3.11, 3.12, and 3.13 before merging.

## Reporting security issues

See `SECURITY.md`.

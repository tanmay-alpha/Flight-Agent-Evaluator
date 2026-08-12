# ADR 0001 — Python project foundation

- **Status:** Accepted
- **Date:** 2026-07-28
- **Stage:** 0 (project definition) — ratified in Stage 1.

## Context

The repository must host a long-lived engineering platform with strict
contracts, reproducible replay, and predictable dependencies. The choices
below govern the foundational toolchain, packaging, layout, and Python
support policy.

## Decision

### Package management — uv

Use [uv](https://docs.astral.sh/uv/) as the sole source of truth for
dependencies and virtual environments.

- Single `pyproject.toml` for project metadata, runtime dependencies, and
  development groups.
- `uv.lock` is committed and frozen in CI (`uv sync --locked --all-groups`).
- No `requirements.txt`, `setup.py`, `setup.cfg`, `Pipfile`, or `poetry.lock`.

### Build backend — `uv_build`

The pure-Python `src/` layout uses the `uv_build` build backend with a
constrained version per the official uv guidance. If a concrete
incompatibility surfaces, the fallback is Hatchling; that decision would be
recorded in a new ADR.

### Layout — single `src/` package

- Single package, single repository. No monorepo, no uv workspace.
- `src/flight_agent_evaluator/` is the importable package root.
- No `microservices/` style splits.
- A workspace is only reconsidered when independently deployable packages
  actually exist.

### Configuration — pyproject only

The single source of truth is `pyproject.toml` for:

- Project metadata.
- Runtime and development dependencies.
- Ruff configuration.
- mypy configuration.
- pytest configuration.
- coverage.py configuration.
- uv configuration.

No `ruff.toml`, `mypy.ini`, `pytest.ini`, `setup.py`, `setup.cfg`, or
`requirements.txt`.

### Python support

- **Minimum:** Python 3.11.
- **Tested:** Python 3.11, 3.12, 3.13.
- Modern built-in generics and union syntax (`X | Y`, `list[X]`, `dict[K, V]`)
  are used unconditionally.
- Timezone-aware datetimes are mandatory; naive datetimes are rejected.

### License

The repository is licensed under the MIT License. This ADR records that
decision: the absence of any pre-existing license at Stage 0 means MIT is
adopted as the default.

## Consequences

- New contributors must install uv; the only supported workflow is
  `uv sync / uv run / uv build`.
- CI must use `uv sync --locked` and pin the uv version used for
  reproducibility.
- Later stages may revisit the build backend only if a concrete incompatibility
  surfaces.

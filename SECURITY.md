# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x | Yes |
| < 0.4 | No |

Security fixes are made on `main` and released as a new 0.4.x patch version. The
`v1.0.0` tag is a historical pre-release snapshot (package version 0.1.0) and is
not supported; see `CHANGELOG.md`.

## Threat model in brief

The evaluator runs locally on inputs that may come from someone else: agent
traces, scenarios, expectations, run bundles and recorded model exchanges.

- **Trace files are untrusted input.** A trace may name a scenario and an
  expectation by relative path. Those paths must stay inside the trace file's
  directory, or an extra root given with `trace evaluate --allow-root DIR`.
  Absolute paths, drive letters, `..` components, NUL bytes and symlinked or
  junctioned ancestors are rejected (`traces/evaluate.py`).
- **JSON is parsed strictly and with limits** (`strict_json.py`). Duplicate
  keys, `NaN`/`Infinity` (including numbers such as `1e999` that overflow to
  infinity), a UTF-8 BOM and invalid UTF-8 are rejected. Documents are limited
  to 5 MiB and 64 levels of nesting by default; trace files are limited to
  5 MiB and the scenarios and expectations they reference to 1 MiB.
- **Secrets are refused in persisted artifacts.** Before a model-exchange
  manifest is written, it is checked for the configured API key, `sk-…` keys,
  `Bearer` tokens and credential-named fields such as `api_key` or
  `authorization`. If any is present, the run fails and nothing is written
  (`agent/model_client.py`, `agent/security.py`). Explicit keys shorter than
  12 characters, such as the placeholder `ollama` for a local server, are not
  treated as secrets, and an `sk-` match needs a left boundary, so ids such as
  `task-<sha256>` are not flagged.
- **The hash chain is unkeyed.** Journals and bundle manifests use plain
  SHA-256. They are tamper-evident only against accidental corruption or naive
  edits. Anyone who can edit a journal can also recompute every hash; nothing
  is signed or MAC'd.

Out of scope: the simulated environment has no real back end (see below).
Model responses are evaluated as data; tool calls they request run only
against the simulated environment.

## Reporting a vulnerability

**Do not file a public GitHub issue for security vulnerabilities.**

Please report vulnerabilities privately through GitHub's
"Suggest a fix" / private vulnerability reporting flow against the repository
issue tracker, or contact the maintainers through the address in their GitHub
profile if one is configured.

When reporting, please include:

- A description of the vulnerability and its impact.
- Reproduction steps, including any payload that triggers it.
- The commit SHA or release tag where the issue was observed.
- Any known mitigations.

We will acknowledge reports within a reasonable time and coordinate disclosure.

## Sensitive material

When contributing, **never commit**:

- API keys, tokens, OAuth credentials, or any form of provider secret.
- Real booking references, passenger names, or other personal information.
- Real flight status data tied to a live booking.
- `.env` files, SSH keys, or cookie stores.
- Judge exchange recordings containing real user PII.

The fixture provider and synthetic fixtures in this repository are
intentionally fictional; any contribution that introduces real credentials or
real personal data will be rejected.

## Simulated environment scope

The simulated airline environment performs **no real mutations**. It does not
connect to any airline booking API, payment processor, or passenger data system.
All booking references, itineraries, and passenger identifiers are synthetic and
explicitly labelled as such.

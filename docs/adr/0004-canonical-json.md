# ADR-0004: Canonical JSON for Deterministic Hashing

## Status

Accepted

## Context

Deterministic hashes are required for idempotency keys, approval payload
verification, and reproducible evaluation runs.  Standard `json.dumps` is
non-deterministic because dict key order, `Decimal` repr, and `datetime`
formatting vary across Python versions and input construction order.

## Decision

Introduce a `canonical_json()` utility (`src/flight_agent_evaluator/canonical.py`)
that applies the following policy:

- **UTF-8** encoding.
- Dict keys sorted lexicographically before serialisation.
- Stable separators (`,` and `:` — no whitespace).
- **No NaN / Infinity** — raises `ValueError` instead.
- `datetime` → ISO 8601 with explicit UTC offset (`+00:00`).
- `UUID` → lowercase 8-4-4-4-12 hex.
- `Decimal` → string without exponent (`format(value, "f")`).
- Other JSON-compatible types pass through unchanged.
- Non-JSON-compatible types raise `ValueError`.

Policy is versioned via a `_CANONICAL_VERSION` constant.  Bumping the version
invalidates all historical hashes but is safe because only the *current*
version is used for new hashes.

A companion `canonical_hash()` function returns the SHA-256 hex digest of the
canonical JSON string.

## Consequences

- **Positive**: deterministic, auditable, versioned hash contract.
- **Positive**: minimal surface area — single function per operation.
- **Trade-off**: callers must ensure values are JSON-serialisable before
  calling; unsupported types raise at runtime.

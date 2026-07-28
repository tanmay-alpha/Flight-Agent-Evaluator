# Security Policy

## Supported versions

Phase 1 is in active development. Only the most recent commit on `main` is
considered supported. Security fixes will be backported as appropriate.

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

The fixture provider and synthetic fixtures in this repository are
intentionally fictional; any contribution that introduces real credentials or
real personal data will be rejected.
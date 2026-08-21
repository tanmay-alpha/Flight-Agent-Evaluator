# Benchmark Methodology & Manifest Integrity

## Benchmark Design Principles

The benchmark assesses flight assistant agent reliability across realistic operational conditions:
- **Disruption Remediation**: Delays, cancellations, misconnections, and weather diversions.
- **Transactional State Operations**: Multi-step rebooking requiring seat holds, passenger approvals, and atomic confirmation.
- **Safety Boundaries**: Prompt injection attempts, unauthorized cancellations, and unapproved fare commitments.
- **Constraint Complexity**: Multi-leg journeys, budget limits, airline preference rules, and seat class constraints.

## Canonical Manifest Binding

Benchmark reproducibility is enforced through immutable JSON manifests:
- Each scenario entry specifies `scenario_id`, `scenario_path`, `scenario_sha256`, `expectation_path`, and `expectation_sha256`.
- `BenchmarkCorpusValidator` strictly verifies file existence and SHA-256 byte parity before benchmark execution commences.
- Benchmark executions bind their results to the canonical manifest digest, preventing silent benchmark drift or scenario mutation.

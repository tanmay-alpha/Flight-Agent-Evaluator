# Benchmark Integrity & Verification Methodology

## 1. Threat Model & Failure Modes Addressed

The Layer 3 Benchmark Integrity redesign addresses critical failure modes in benchmark harnesses:

| Defect ID | Vulnerability / Defect | Remediation & Invariant |
|---|---|---|
| **D1** | Ad-hoc generated expectations (`_build_default_expectation`) synthesized on the fly | Authoritative runs mandate authored `TrajectoryExpectation` loaded from disk. |
| **D2** | Fake model aliases (`gpt-4o` mapped to `ScriptedOracleAgent`) | `BenchmarkAgentRegistry` requires exact agent registration; unknown IDs fail closed. |
| **D3** | Silent fallback to `jfk-lhr-delay` on missing scenario | Nonexistent scenario IDs raise `FileNotFoundError` or `BenchmarkIntegrityError`. |
| **D4** | Tamper vulnerability in scenario or expectation resources | Raw SHA-256 byte verification prior to parsing; canonical manifest digest sealing. |
| **D5** | Non-manifest files executed by directory globbing | Manifest-bound execution: only scenarios declared in the manifest are executed. |
| **D6** | Divergent CLI and library benchmark pipelines | Single unified `CanonicalBenchmarkEngine` backing both CLI subcommands and library API. |

---

## 2. Manifest Canonicalization & Digest Computation

The canonical manifest digest is computed over a deterministic JSON serialization:
- All dictionary keys are lexicographically sorted.
- Volatile fields (such as `manifest_digest` itself and external timestamps) are excluded or normalized.
- Separators are compact (`,`, `:`).
- SHA-256 hash is represented as 64 lowercase hexadecimal characters.

```python
# Deterministic representation computation
payload = json.dumps(raw_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
canonical_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

---

## 3. Authoritative Benchmark Corpus

The authoritative corpus consists of **24 scenarios** and **24 authored expectation graphs**:
- Scenarios are validated for schema conformity, objective specifications, and tool call constraints.
- Expectation graphs define valid execution paths, argument assertions via JSON pointers, and strict safety constraints.
- Any modification to either scenario or expectation files alters its SHA-256 digest, immediately invalidating the manifest.

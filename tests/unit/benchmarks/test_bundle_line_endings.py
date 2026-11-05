"""Persisted benchmark bundles must be byte-identical across operating systems."""

from __future__ import annotations

from pathlib import Path

from flight_agent_evaluator.benchmarks.engine import CanonicalBenchmarkEngine


def test_persisted_bundle_files_use_lf_line_endings(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    CanonicalBenchmarkEngine().run_benchmark(
        manifest_path="builtin:demo-v1", agent_ids=["scripted-oracle"], output_dir=out
    )
    written = [p for p in out.rglob("*") if p.is_file()]
    assert {p.name for p in written} >= {"run.json", "summary.json", "README.md"}
    assert [p.name for p in written if b"\r\n" in p.read_bytes()] == []

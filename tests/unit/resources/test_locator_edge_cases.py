"""Targeted edge case tests to maximize branch coverage across resources and locators."""

from __future__ import annotations

from pathlib import Path

import pytest

from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
    ManifestValidationError,
)
from flight_agent_evaluator.benchmarks.validator import BenchmarkCorpusValidator
from flight_agent_evaluator.engine.scenario_loader import (
    ScenarioLoader,
    ScenarioLoaderError,
)
from flight_agent_evaluator.resources import (
    BuiltinResourceLocator,
    BuiltinResourceNotFound,
    ExternalResourceLocator,
    ExternalResourceNotFound,
    PackagedResourceIntegrityError,
    ResourceError,
    ResourceKind,
    ResourceOrigin,
    ResourceRef,
    get_builtin_locator,
)


def test_builtin_locator_edge_cases():
    loc = BuiltinResourceLocator()

    # Non-directory iter_children returns empty list
    assert loc.iter_children("nonexistent_folder_abc", ResourceKind.SCENARIO) == []

    # materialize missing resource raises BuiltinResourceNotFound
    ref_missing = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path="scenarios/does_not_exist.json",
        kind=ResourceKind.SCENARIO,
    )
    with pytest.raises(BuiltinResourceNotFound), loc.materialize(ref_missing):
        pass

    # decode failure in read_text
    ref_fix = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path="fixtures/flight_status_delayed.json",
        kind=ResourceKind.FIXTURE,
    )
    # Using invalid encoding
    with pytest.raises(PackagedResourceIntegrityError):
        loc.read_text(ref_fix, encoding="ascii_invalid_nonexistent")


def test_external_locator_edge_cases(tmp_path: Path):
    loc = ExternalResourceLocator(root_dir=tmp_path)
    assert loc.root_dir == tmp_path

    # Non-dir iter_children
    assert loc.iter_children("non_dir", ResourceKind.SCENARIO) == []

    # Absolute path resolution
    sample_file = tmp_path / "sample.json"
    sample_file.write_bytes(b"\xff\xfe\x00\x00")  # Non-utf8 binary data

    ref = ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path=str(sample_file.resolve()),
        kind=ResourceKind.SCENARIO,
    )
    assert loc.exists(ref)

    # Decoding error raises ResourceError
    with pytest.raises(ResourceError, match="could not be decoded"):
        loc.read_text(ref, encoding="utf-8")

    # Materialize missing file
    ref_missing = ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path="nonexistent.json",
        kind=ResourceKind.SCENARIO,
    )
    with pytest.raises(ExternalResourceNotFound), loc.materialize(ref_missing):
        pass


def test_scenario_loader_edge_cases(tmp_path: Path):
    loader = ScenarioLoader()

    # Loading with external locator
    sample_file = tmp_path / "valid_sc.json"
    raw_bytes = get_builtin_locator().read_bytes(
        ResourceRef(
            origin=ResourceOrigin.BUILTIN,
            logical_path="scenarios/jfk-lhr-delay.json",
            kind=ResourceKind.SCENARIO,
        )
    )
    sample_file.write_bytes(raw_bytes)

    ext_loc = ExternalResourceLocator(root_dir=tmp_path)
    ref = ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path="valid_sc.json",
        kind=ResourceKind.SCENARIO,
    )
    loaded = loader.load_resource(ref, ext_loc)
    assert loaded.scenario.scenario_id.id == "jfk-lhr-delay"

    # load_from_path with mismatched digest
    with pytest.raises(ScenarioLoaderError, match="digest mismatch"):
        loader.load_from_path(sample_file, expected_sha256="0" * 64)


def test_benchmark_loader_and_validator_edge_cases(tmp_path: Path):
    bm_loader = BenchmarkManifestLoader()

    # Builtin demo-v1
    manifest, cases = bm_loader.load_builtin("demo-v1", verify_resources=True)
    assert manifest.benchmark_id == "demo-v1"
    assert len(cases) == 4

    # Load nonexistent builtin
    with pytest.raises((BenchmarkIntegrityError, ResourceError)):
        bm_loader.load_builtin("nonexistent-bench-xyz")

    # Invalid JSON file
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("invalid { json", encoding="utf-8")
    with pytest.raises(ManifestValidationError):
        bm_loader.load_manifest(bad_json)

    # Validator with missing manifest
    validator = BenchmarkCorpusValidator()
    report = validator.validate_manifest_file(tmp_path / "missing.json")
    assert report.valid is False
    assert any(e.code == "MANIFEST_NOT_FOUND" for e in report.errors)

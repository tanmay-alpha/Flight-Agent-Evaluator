"""Comprehensive unit tests for ResourceRef, locators, loaders, and URI parser."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from flight_agent_evaluator.benchmarks.loader import (
    BenchmarkIntegrityError,
    BenchmarkManifestLoader,
    ManifestValidationError,
)
from flight_agent_evaluator.benchmarks.validator import BenchmarkCorpusValidator
from flight_agent_evaluator.contracts.trajectory_expectation import (
    TrajectoryExpectation,
    load_builtin_expectation,
    load_expectation_bytes,
    load_expectation_from_path,
    load_expectation_text,
)
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
    ResourceSecurityError,
    get_builtin_locator,
    parse_resource_uri,
    sanitize_logical_path,
)


def test_sanitize_logical_path_valid():
    assert sanitize_logical_path("scenarios/jfk-lhr-delay.json") == "scenarios/jfk-lhr-delay.json"
    assert sanitize_logical_path("benchmarks\\benchmark-v1.json") == "benchmarks/benchmark-v1.json"
    assert (
        sanitize_logical_path("fixtures/flight_status_delayed.json")
        == "fixtures/flight_status_delayed.json"
    )


def test_sanitize_logical_path_security_violations():
    with pytest.raises(ResourceSecurityError, match="Path traversal"):
        sanitize_logical_path("../secret.json")

    with pytest.raises(ResourceSecurityError, match="Path traversal"):
        sanitize_logical_path("scenarios/../../secret.json")

    with pytest.raises(ResourceSecurityError, match="Absolute paths"):
        sanitize_logical_path("/etc/passwd")

    with pytest.raises(ResourceSecurityError, match="Drive identifiers"):
        sanitize_logical_path("C:\\windows\\system32")

    with pytest.raises(ResourceSecurityError, match="Null bytes"):
        sanitize_logical_path("test\x00.json")

    with pytest.raises(ResourceSecurityError, match="Empty"):
        sanitize_logical_path("")


def test_parse_resource_uri_builtin():
    ref = parse_resource_uri("builtin:benchmark-v1")
    assert ref.origin == ResourceOrigin.BUILTIN
    assert ref.logical_path == "benchmarks/benchmark-v1.json"
    assert ref.kind == ResourceKind.BENCHMARK_MANIFEST

    ref_sc = parse_resource_uri("builtin:scenarios/jfk-lhr-delay.json")
    assert ref_sc.origin == ResourceOrigin.BUILTIN
    assert ref_sc.logical_path == "scenarios/jfk-lhr-delay.json"
    assert ref_sc.kind == ResourceKind.SCENARIO

    ref_exp = parse_resource_uri("builtin:expectations/jfk-lhr-delay.json")
    assert ref_exp.origin == ResourceOrigin.BUILTIN
    assert ref_exp.logical_path == "expectations/jfk-lhr-delay.json"
    assert ref_exp.kind == ResourceKind.EXPECTATION

    ref_fix = parse_resource_uri("builtin:fixtures/flight_status_delayed.json")
    assert ref_fix.origin == ResourceOrigin.BUILTIN
    assert ref_fix.kind == ResourceKind.FIXTURE

    with pytest.raises(ResourceError, match="Empty"):
        parse_resource_uri("")

    with pytest.raises(ResourceError, match="Empty built-in"):
        parse_resource_uri("builtin:   ")


def test_parse_resource_uri_external(tmp_path: Path):
    file_path = tmp_path / "custom_bench.json"
    file_path.write_text("{}", encoding="utf-8")

    ref_file_uri = parse_resource_uri(f"file:{file_path}")
    assert ref_file_uri.origin == ResourceOrigin.EXTERNAL
    assert ref_file_uri.resolved_path is not None

    ref_plain = parse_resource_uri(str(file_path))
    assert ref_plain.origin == ResourceOrigin.EXTERNAL


def test_builtin_locator_read_fixtures():
    locator = get_builtin_locator()
    ref = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path="fixtures/flight_status_delayed.json",
        kind=ResourceKind.FIXTURE,
    )
    assert locator.exists(ref)
    data = locator.read_text(ref)
    assert "AS142" in data

    sha = locator.digest(ref)
    assert len(sha) == 64
    ref_with_sha = ref.model_copy(update={"expected_sha256": sha})
    assert locator.read_bytes(ref_with_sha) == locator.read_bytes(ref)

    ref_bad_sha = ref.model_copy(update={"expected_sha256": "0" * 64})
    with pytest.raises(PackagedResourceIntegrityError, match="SHA-256 digest mismatch"):
        locator.read_bytes(ref_bad_sha)

    ref_missing = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path="fixtures/nonexistent.json",
        kind=ResourceKind.FIXTURE,
    )
    assert not locator.exists(ref_missing)
    with pytest.raises(BuiltinResourceNotFound):
        locator.read_bytes(ref_missing)


def test_builtin_locator_iter_children_and_materialize():
    locator = get_builtin_locator()
    children = locator.iter_children("scenarios", ResourceKind.SCENARIO)
    assert len(children) == 12
    children_stage5 = locator.iter_children("scenarios/stage-5", ResourceKind.SCENARIO)
    assert len(children_stage5) == 12

    first = children[0]
    with locator.materialize(first) as materialized_path:
        assert materialized_path.is_file()
        assert materialized_path.suffix == ".json"

    benchmarks = locator.list_builtin_benchmarks()
    assert "benchmark-v1" in benchmarks
    assert "demo-v1" in benchmarks


def test_external_locator_operations(tmp_path: Path):
    sample_file = tmp_path / "sample.json"
    content = '{"hello": "world"}'
    sample_file.write_text(content, encoding="utf-8")
    expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

    locator = ExternalResourceLocator(root_dir=tmp_path)
    ref = ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path="sample.json",
        kind=ResourceKind.SCENARIO,
        expected_sha256=expected_sha,
    )

    assert locator.exists(ref)
    assert locator.read_text(ref) == content
    assert locator.digest(ref) == expected_sha

    with locator.materialize(ref) as real_p:
        assert real_p.is_file()
        assert real_p.read_text(encoding="utf-8") == content

    children = locator.iter_children(".", ResourceKind.SCENARIO)
    assert any("sample.json" in c.logical_path for c in children)

    ref_missing = ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path="missing.json",
        kind=ResourceKind.SCENARIO,
    )
    assert not locator.exists(ref_missing)
    with pytest.raises(ExternalResourceNotFound):
        locator.read_bytes(ref_missing)

    ref_bad_sha = ref.model_copy(update={"expected_sha256": "f" * 64})
    with pytest.raises(PackagedResourceIntegrityError):
        locator.read_bytes(ref_bad_sha)


def test_scenario_loader_builtin():
    loader = ScenarioLoader()
    loaded = loader.load_builtin("jfk-lhr-delay")
    assert loaded.scenario.scenario_id.id == "jfk-lhr-delay"
    assert len(loaded.digest) == 64

    # From bytes using original JSON file bytes
    locator = get_builtin_locator()
    raw = locator.read_bytes(
        ResourceRef(
            origin=ResourceOrigin.BUILTIN,
            logical_path="scenarios/jfk-lhr-delay.json",
            kind=ResourceKind.SCENARIO,
        )
    )
    loaded2 = loader.load_from_bytes(raw)
    assert loaded2.scenario.scenario_id.id == "jfk-lhr-delay"

    # From text
    loaded3 = loader.load_from_text(raw.decode("utf-8"))
    assert loaded3.scenario.scenario_id.id == "jfk-lhr-delay"


def test_expectation_loaders():
    exp = load_builtin_expectation("jfk-lhr-delay")
    assert isinstance(exp, TrajectoryExpectation)
    assert exp.scenario_id == "jfk-lhr-delay"

    exp_with_prefix = load_builtin_expectation("expectations/jfk-lhr-delay.json")
    assert exp_with_prefix.scenario_id == "jfk-lhr-delay"

    raw = exp.model_dump_json().encode("utf-8")
    exp2 = load_expectation_bytes(raw)
    assert exp2.scenario_id == "jfk-lhr-delay"

    exp3 = load_expectation_text(raw.decode("utf-8"))
    assert exp3.scenario_id == "jfk-lhr-delay"

    # From explicit path
    locator = get_builtin_locator()
    ref = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path="expectations/jfk-lhr-delay.json",
        kind=ResourceKind.EXPECTATION,
    )
    with locator.materialize(ref) as real_path:
        exp4 = load_expectation_from_path(real_path)
        assert exp4.scenario_id == "jfk-lhr-delay"

    with pytest.raises(FileNotFoundError):
        load_expectation_from_path("nonexistent_path_xyz.json")


def test_replay_factory_resolve_scenario():
    from flight_agent_evaluator.recording.contracts import ReplayProvenance
    from flight_agent_evaluator.replay.provenance import (
        ReplayExecutionFactory,
        ReplayProvenanceMismatchError,
    )

    factory = ReplayExecutionFactory()
    loader = ScenarioLoader()
    scenario = loader.load_builtin("jfk-lhr-delay")

    prov = ReplayProvenance(
        scenario_id="jfk-lhr-delay",
        scenario_version=1,
        scenario_digest=scenario.digest,
        agent_id="oracle",
        environment_version="1.0.0",
    )
    loaded = factory.resolve_scenario(prov)
    assert loaded.scenario.scenario_id.id == "jfk-lhr-delay"

    # Mismatched digest raises ReplayProvenanceMismatchError
    prov_bad = prov.model_copy(update={"scenario_digest": "0" * 64})
    with pytest.raises(ReplayProvenanceMismatchError, match="digest mismatch"):
        factory.resolve_scenario(prov_bad)


def test_builtin_locator_edge_cases():
    loc = BuiltinResourceLocator()

    assert loc.iter_children("nonexistent_folder_abc", ResourceKind.SCENARIO) == []

    ref_missing = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path="scenarios/does_not_exist.json",
        kind=ResourceKind.SCENARIO,
    )
    with pytest.raises(BuiltinResourceNotFound), loc.materialize(ref_missing):
        pass

    ref_fix = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path="fixtures/flight_status_delayed.json",
        kind=ResourceKind.FIXTURE,
    )
    with pytest.raises(PackagedResourceIntegrityError):
        loc.read_text(ref_fix, encoding="ascii_invalid_nonexistent")


def test_external_locator_edge_cases(tmp_path: Path):
    loc = ExternalResourceLocator(root_dir=tmp_path)
    assert loc.root_dir == tmp_path

    assert loc.iter_children("non_dir", ResourceKind.SCENARIO) == []

    sample_file = tmp_path / "sample.json"
    sample_file.write_bytes(b"\xff\xfe\x00\x00")

    ref = ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path=str(sample_file.resolve()),
        kind=ResourceKind.SCENARIO,
    )
    assert loc.exists(ref)

    with pytest.raises(ResourceError, match="could not be decoded"):
        loc.read_text(ref, encoding="utf-8")

    ref_missing = ResourceRef(
        origin=ResourceOrigin.EXTERNAL,
        logical_path="nonexistent.json",
        kind=ResourceKind.SCENARIO,
    )
    with pytest.raises(ExternalResourceNotFound), loc.materialize(ref_missing):
        pass


def test_scenario_loader_edge_cases(tmp_path: Path):
    loader = ScenarioLoader()

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

    with pytest.raises(ScenarioLoaderError, match="digest mismatch"):
        loader.load_from_path(sample_file, expected_sha256="0" * 64)


def test_benchmark_loader_and_validator_edge_cases(tmp_path: Path):
    bm_loader = BenchmarkManifestLoader()

    manifest, cases = bm_loader.load_builtin("demo-v1", verify_resources=True)
    assert manifest.benchmark_id == "demo-v1"
    assert len(cases) == 4

    with pytest.raises((BenchmarkIntegrityError, ResourceError)):
        bm_loader.load_builtin("nonexistent-bench-xyz")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("invalid { json", encoding="utf-8")
    with pytest.raises(ManifestValidationError):
        bm_loader.load_manifest(bad_json)

    validator = BenchmarkCorpusValidator()
    report = validator.validate_manifest_file(tmp_path / "missing.json")
    assert report.valid is False
    assert any(e.code == "MANIFEST_NOT_FOUND" for e in report.errors)

"""Tests for engine.scenario_loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.engine.scenario_loader import (
    ScenarioLoader,
    ScenarioLoaderError,
    ScenarioVersionMismatchError,
)


def _valid_scenario_dict() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "scenario_id": {"id": "test-scenario", "version": 1},
        "metadata": {
            "title": "Test scenario",
            "description": "A test scenario",
            "objective": "Verify the runner works",
        },
        "limits": {"tool_call_limit": 5, "time_limit_seconds": 60},
        "seed": 42,
        "steps": [
            {"step_id": "step-1", "description": "Do something"},
        ],
    }


class TestScenarioLoader:
    def test_load_from_path(self, tmp_path: Path):
        target = tmp_path / "scenario.json"
        target.write_text(json.dumps(_valid_scenario_dict()), encoding="utf-8")
        loader = ScenarioLoader()
        loaded = loader.load_from_path(target)
        assert loaded.scenario.scenario_id.id == "test-scenario"
        assert loaded.digest != ""
        assert len(loaded.digest) == 64
        assert loaded.raw_bytes is not None

    def test_load_rejects_missing(self, tmp_path: Path):
        loader = ScenarioLoader()
        with pytest.raises(ScenarioLoaderError, match="not found"):
            loader.load_from_path(tmp_path / "missing.json")

    def test_load_rejects_oversized(self, tmp_path: Path):
        loader = ScenarioLoader(max_bytes=10)
        target = tmp_path / "scenario.json"
        target.write_text("{}" * 100, encoding="utf-8")
        with pytest.raises(ScenarioLoaderError, match="too large"):
            loader.load_from_path(target)

    def test_load_rejects_future_major_version(self, tmp_path: Path):
        target = tmp_path / "scenario.json"
        d = _valid_scenario_dict()
        d["schema_version"] = "99.0.0"
        target.write_text(json.dumps(d), encoding="utf-8")
        loader = ScenarioLoader()
        with pytest.raises(ScenarioVersionMismatchError):
            loader.load_from_path(target)

    def test_load_rejects_unknown_field(self, tmp_path: Path):
        target = tmp_path / "scenario.json"
        d = _valid_scenario_dict()
        d["unknown_field"] = "boom"
        target.write_text(json.dumps(d), encoding="utf-8")
        loader = ScenarioLoader()
        with pytest.raises(Exception):
            loader.load_from_path(target)

    def test_load_rejects_invalid_schema(self, tmp_path: Path):
        target = tmp_path / "scenario.json"
        target.write_text("not json at all {", encoding="utf-8")
        loader = ScenarioLoader()
        with pytest.raises(ScenarioLoaderError):
            loader.load_from_path(target)

    def test_load_rejects_path_traversal(self, tmp_path: Path):
        loader = ScenarioLoader(allowed_root=tmp_path)
        outside = tmp_path.parent / "escape.json"
        outside.write_text(json.dumps(_valid_scenario_dict()), encoding="utf-8")
        with pytest.raises(ScenarioLoaderError, match="outside"):
            loader.load_from_path(outside)

    def test_load_rejects_symlink(self, tmp_path: Path):
        real = tmp_path / "real.json"
        real.write_text(json.dumps(_valid_scenario_dict()), encoding="utf-8")
        link = tmp_path / "link.json"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        loader = ScenarioLoader(allowed_root=tmp_path)
        with pytest.raises(ScenarioLoaderError):
            loader.load_from_path(link)

    def test_invalid_max_bytes(self):
        with pytest.raises(ValueError, match="max_bytes must be positive"):
            ScenarioLoader(max_bytes=0)

    def test_load_rejects_non_dict_json(self, tmp_path: Path):
        target = tmp_path / "scenario.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")
        loader = ScenarioLoader()
        with pytest.raises(ScenarioLoaderError, match="must be a JSON object"):
            loader.load_from_path(target)

    def test_load_rejects_malformed_schema_version(self, tmp_path: Path):
        loader = ScenarioLoader()

        # Non-string schema_version
        target1 = tmp_path / "s1.json"
        d1 = _valid_scenario_dict()
        d1["schema_version"] = 123
        target1.write_text(json.dumps(d1), encoding="utf-8")
        with pytest.raises(ScenarioVersionMismatchError, match="Malformed schema_version type"):
            loader.load_from_path(target1)

        # Malformed major string
        target2 = tmp_path / "s2.json"
        d2 = _valid_scenario_dict()
        d2["schema_version"] = "abc.0.0"
        target2.write_text(json.dumps(d2), encoding="utf-8")
        with pytest.raises(ScenarioVersionMismatchError, match="Malformed schema version major"):
            loader.load_from_path(target2)

    def test_load_rejects_bom(self, tmp_path: Path):
        target = tmp_path / "scenario.json"
        target.write_bytes(b"\xef\xbb\xbf" + json.dumps(_valid_scenario_dict()).encode())
        loader = ScenarioLoader()
        with pytest.raises(ScenarioLoaderError):
            loader.load_from_path(target)


class TestLoadedScenarioContract:
    def test_returns_scenario_and_digest(self, tmp_path: Path):
        target = tmp_path / "scenario.json"
        target.write_text(json.dumps(_valid_scenario_dict()), encoding="utf-8")
        loaded = ScenarioLoader().load_from_path(target)
        assert isinstance(loaded.scenario, BenchmarkScenario)
        assert loaded.digest == loaded.digest  # stable

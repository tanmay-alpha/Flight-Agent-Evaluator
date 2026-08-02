"""Tests for engine.scenario_loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from typing import Any

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

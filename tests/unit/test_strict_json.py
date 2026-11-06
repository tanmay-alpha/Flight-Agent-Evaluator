"""Strict JSON parsing: every rejection that stops two readers seeing different data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader, ScenarioLoaderError
from flight_agent_evaluator.strict_json import StrictJSONError, load_strict_path, loads_strict


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b'{"a": 1, "a": 2}', "duplicate key"),
        (b'{"outer": {"k": 1, "k": 1}}', "duplicate key"),
        (b'{"x": NaN}', "non-finite"),
        (b'{"x": 1e999}', "non-finite"),
        (b'{"x": -1e999}', "non-finite"),
        (b'{"x": -Infinity}', "non-finite"),
        (b"\xef\xbb\xbf{}", "BOM"),
        (b'{"x": "\xff"}', "invalid UTF-8"),
        (b'{"x": ', "invalid JSON"),
        (b"[" * 70 + b"]" * 70, "nesting"),
        (b"[" * 5000 + b"]" * 5000, "nesting"),
    ],
)
def test_rejects_ambiguous_or_unbounded_input(payload: bytes, reason: str) -> None:
    with pytest.raises(StrictJSONError, match=reason):
        loads_strict(payload)


def test_rejects_oversized_input_before_parsing() -> None:
    with pytest.raises(StrictJSONError, match="exceeds"):
        loads_strict(b"[" + b"1," * 100 + b"1]", max_bytes=50)


def test_preserves_empty_containers_and_structure() -> None:
    assert loads_strict(b'{"a": {}, "b": [], "c": [{"d": {}}], "e": 1.5}') == {
        "a": {},
        "b": [],
        "c": [{"d": {}}],
        "e": 1.5,
    }


def test_path_reader_bounds_bytes_read(tmp_path: Path) -> None:
    big = tmp_path / "big.json"
    big.write_bytes(b'"' + b"x" * 1000 + b'"')
    with pytest.raises(StrictJSONError, match="exceeds"):
        load_strict_path(big, max_bytes=100)


def test_scenario_loader_keeps_empty_objects() -> None:
    # The previous pairs-based parser decoded {} as [] and failed dict validation.
    doc = loads_strict(Path("resources/scenarios/lax-sfo-ontime.json").read_bytes())
    doc["initial_state"] = {}
    loaded = ScenarioLoader().load_from_bytes(json.dumps(doc).encode("utf-8"))
    assert loaded.scenario.initial_state == {}


def test_scenario_loader_rejects_pair_arrays_as_objects() -> None:
    with pytest.raises(ScenarioLoaderError, match="JSON object"):
        ScenarioLoader().load_from_bytes(b'[["schema_version", "1.0.0"]]')

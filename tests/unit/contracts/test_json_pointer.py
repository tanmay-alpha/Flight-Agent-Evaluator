"""Unit tests for strict RFC 6901 JSON pointer utility."""

import pytest

from flight_agent_evaluator.contracts.json_pointer import MISSING, resolve_json_pointer


def test_resolve_json_pointer_root():
    doc = {"a": 1, "b": [10, 20]}
    assert resolve_json_pointer(doc, "") == doc


def test_resolve_json_pointer_simple():
    doc = {"a": 1, "b": {"c": "hello"}}
    assert resolve_json_pointer(doc, "/a") == 1
    assert resolve_json_pointer(doc, "/b/c") == "hello"


def test_resolve_json_pointer_missing_key():
    doc = {"a": 1}
    assert resolve_json_pointer(doc, "/missing") is MISSING
    assert resolve_json_pointer(doc, "/a/b") is MISSING


def test_resolve_json_pointer_null_value():
    doc = {"a": None}
    resolved = resolve_json_pointer(doc, "/a")
    assert resolved is None
    assert resolved is not MISSING


def test_resolve_json_pointer_array_indexing():
    doc = {"items": ["first", "second", None]}
    assert resolve_json_pointer(doc, "/items/0") == "first"
    assert resolve_json_pointer(doc, "/items/1") == "second"
    assert resolve_json_pointer(doc, "/items/2") is None
    assert resolve_json_pointer(doc, "/items/3") is MISSING


def test_resolve_json_pointer_rfc6901_unescaping():
    doc = {"a/b": 100, "c~d": 200, "~": 300, "/": 400}
    assert resolve_json_pointer(doc, "/a~1b") == 100
    assert resolve_json_pointer(doc, "/c~0d") == 200
    assert resolve_json_pointer(doc, "/~0") == 300
    assert resolve_json_pointer(doc, "/~1") == 400


def test_resolve_json_pointer_invalid_syntax():
    doc = {"a": 1}
    with pytest.raises(ValueError, match="must start with '/'"):
        resolve_json_pointer(doc, "invalid")

    with pytest.raises(ValueError, match="depth"):
        resolve_json_pointer(doc, "/" + "/".join(["x"] * 40))

    with pytest.raises(ValueError, match="escape sequence"):
        resolve_json_pointer(doc, "/a~2")

    with pytest.raises(ValueError, match="unescaped '~'"):
        resolve_json_pointer(doc, "/a~")


def test_resolve_json_pointer_invalid_array_index():
    doc = {"items": [1, 2]}
    with pytest.raises(ValueError, match="Invalid array index"):
        resolve_json_pointer(doc, "/items/abc")

    with pytest.raises(ValueError, match="Invalid array index"):
        resolve_json_pointer(doc, "/items/01")

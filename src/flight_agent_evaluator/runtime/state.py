"""Validated state snapshot for the runtime engine.

State values must be JSON-compatible: strings, numbers, booleans, lists,
or nested dicts of such values. Decimal is also accepted for monetary
amounts. Anything else is rejected at construction time.

State is immutable: transitions produce a new ``StateSnapshot`` via
:meth:`with_data` or :meth:`with_path` rather than mutating in place.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from decimal import Decimal
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from flight_agent_evaluator.contracts.base import ContractModel


def _validate_json_compatible(value: Any) -> None:
    """Walk *value*; raise ValueError if anything is not JSON-compatible."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, Decimal):
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"Dict key must be str, got {type(k).__name__}")
            _validate_json_compatible(v)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            _validate_json_compatible(item)
        return
    raise ValueError(f"State value must be JSON-compatible, got {type(value).__name__}")


class StateSnapshot(ContractModel):
    """A deterministic, JSON-compatible snapshot of run state.

    The snapshot is frozen at the Pydantic level; use :meth:`with_data`
    or :meth:`with_path` to produce a new snapshot with updated values.
    """

    model_config = ConfigDict(frozen=True, validate_default=True)

    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def _validate_data(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"State data must be a dict, got {type(value).__name__}")
        _validate_json_compatible(value)
        return dict(value)

    def with_data(self, update_data: dict[str, Any]) -> StateSnapshot:
        """Return a new ``StateSnapshot`` with *update_data* merged into state.

        The original snapshot is not modified.
        """
        new_data = deepcopy(dict(self.data))
        new_data.update(update_data)
        return StateSnapshot(data=new_data)

    def with_path(self, path: str, value: Any) -> StateSnapshot:
        """Return a new ``StateSnapshot`` with *path* set to *value*.

        *path* is a dotted path, e.g. ``"bookings.b-1.state"``. The path
        must resolve into an existing nested dict structure; missing
        intermediate dicts are created as empty dicts.
        """
        if not path:
            raise ValueError("path must not be empty")
        parts = [p for p in path.split(".") if p]
        new_data: dict[str, Any] = deepcopy(dict(self.data))
        cur: Any = new_data
        for part in parts[:-1]:
            existing = cur.get(part)
            if existing is None:
                cur[part] = {}
            elif not isinstance(existing, dict):
                raise ValueError(
                    f"Cannot set nested path {path!r}: intermediate {part!r} is not a dict"
                )
            cur = cur[part]
        cur[parts[-1]] = value
        return StateSnapshot(data=new_data)

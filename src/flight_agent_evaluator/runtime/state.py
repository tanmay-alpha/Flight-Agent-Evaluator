"""Validated state snapshot for the runtime engine.

State values must be JSON-compatible: strings, numbers, booleans, lists,
or nested dicts of such values. Decimal is also accepted for monetary
amounts. Anything else is rejected at construction time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
                raise ValueError(
                    f"Dict key must be str, got {type(k).__name__}"
                )
            _validate_json_compatible(v)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            _validate_json_compatible(item)
        return
    raise ValueError(
        f"State value must be JSON-compatible, got {type(value).__name__}"
    )


class _RawStateData(dict[str, Any]):
    """A plain dict subclass that accepts any keys and passes them through
    validation without Pydantic treating keys as model fields."""


class StateSnapshot(ContractModel):
    """A deterministic, JSON-compatible snapshot of run state."""

    model_config = ConfigDict(frozen=True, validate_default=True)

    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def _validate_data(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(
                f"State data must be a dict, got {type(value).__name__}"
            )
        _validate_json_compatible(value)
        return dict(value)
"""Strict JSONL contracts for independent labels and explicit adjudication."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import ConfigDict, Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.strict_json import loads_strict

Score = Annotated[int, Field(strict=True, ge=0, le=4)] | Literal["cannot_judge"]
BinaryLabel = Literal["yes", "no", "unclear"]
Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class CriterionScores(ContractModel):
    """All six criteria are required; missing evidence is not a zero score."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    groundedness: Score
    constraint_awareness: Score
    uncertainty_communication: Score
    completeness: Score
    helpfulness: Score
    clarity: Score


class Labels(ContractModel):
    """Human assessments of the response and of observable trajectory outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scores: CriterionScores
    task_completed: BinaryLabel
    unsafe_action: BinaryLabel
    misleading_claim: BinaryLabel


class Annotation(Labels):
    """One independently submitted annotation for one blinded task."""

    annotator_id: Identifier
    task_id: Identifier
    rationale: str = Field(min_length=1, pattern=r"\S")
    time_spent_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class Adjudication(ContractModel):
    """Explicit final human labels; never filled by a majority-vote algorithm."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    adjudicator_id: Identifier
    task_id: Identifier
    final_labels: Labels
    reason: str = Field(min_length=1, pattern=r"\S")


Record = TypeVar("Record", Annotation, Adjudication)


def load_records(paths: list[Path], record_type: type[Record]) -> list[Record]:
    """Read strict JSONL, rejecting duplicate submissions across files."""
    records: list[Record] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        with path.open("rb") as handle:
            for line_number, raw in enumerate(handle, 1):
                record = record_type.model_validate(
                    loads_strict(raw, source=f"{path.name}:{line_number}")
                )
                owner = record.annotator_id if isinstance(record, Annotation) else "adjudication"
                key = (owner, record.task_id)
                if key in seen:
                    raise ValueError(f"duplicate submission for {owner}/{record.task_id}")
                seen.add(key)
                records.append(record)
    return records

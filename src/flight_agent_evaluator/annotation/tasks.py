"""Public, verdict-free task projection shared with benchmark artifact producers."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from flight_agent_evaluator.contracts.base import ContractModel


def canonical_json(value: Any) -> str:
    """Encode deterministic strict JSON without wall-clock metadata."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def deterministic_task_id(
    public_task: str,
    trusted_observations: list[dict[str, Any]],
    final_response: str | None,
) -> str:
    """Address only annotation-visible content, never evaluator verdicts or model identity."""
    content = {
        "public_task": public_task,
        "trusted_observations": trusted_observations,
        "final_response": final_response,
    }
    return "task-" + hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest()


class ExportTask(ContractModel):
    """A blind task; response text and tool-returned prose remain untrusted claims."""

    task_id: str = Field(pattern=r"^task-[0-9a-f]{64}$")
    public_task: str
    trusted_observations: list[dict[str, Any]]
    final_response: str | None

    @model_validator(mode="after")
    def _bind_content(self) -> ExportTask:
        if self.task_id != deterministic_task_id(
            self.public_task, self.trusted_observations, self.final_response
        ):
            raise ValueError("task_id does not match annotation content")
        return self


def make_task(
    public_task: str,
    trusted_observations: list[dict[str, Any]],
    final_response: str | None,
) -> ExportTask:
    """Build a deterministic task from authenticated environment observations."""
    return ExportTask(
        task_id=deterministic_task_id(public_task, trusted_observations, final_response),
        public_task=public_task,
        trusted_observations=trusted_observations,
        final_response=final_response,
    )


class ExportManifest(ContractModel):
    """Strict digest inventory with no model/run lookup that could unblind annotators."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["annotation-export-v1"]
    rubric_version: Literal["judge-rubric-v1"]
    seed: int
    annotators: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]]
    source_cases: int = Field(ge=1)
    tasks: int = Field(ge=1)
    files: dict[str, Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]]
    task_digests: dict[
        Annotated[str, Field(pattern=r"^task-[0-9a-f]{64}$")],
        Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    ]
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

"""Security hardening: replay outcome statuses, scenario ids, run ids, loader limits."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.contracts.scenarios import ScenarioIdentifier
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader, ScenarioLoaderError
from flight_agent_evaluator.recording.contracts import (
    BehaviourVerificationStatus,
    RecordingIntegrityStatus,
    ReplayReport,
)

SCENARIO = Path("resources/scenarios/lax-sfo-ontime.json")
Provenance = Literal["verified", "mismatch", "unavailable"]


def test_incomplete_bundle_never_reports_success() -> None:
    report = _report(BehaviourVerificationStatus.VERIFIED).model_copy(
        update={"integrity_status": RecordingIntegrityStatus.INCOMPLETE}
    )
    assert report.status == "recording_incomplete"


def _report(
    behaviour: BehaviourVerificationStatus | None, provenance: Provenance = "verified"
) -> ReplayReport:
    return ReplayReport(
        recording_run_id="r",
        mode="verification",
        integrity_status=RecordingIntegrityStatus.VERIFIED,
        behaviour_status=behaviour,
        original_journal_digest="0" * 64,
        provenance_status=provenance,
    )


@pytest.mark.parametrize(
    ("behaviour", "provenance", "expected"),
    [
        (BehaviourVerificationStatus.VERIFIED, "verified", "behaviour_verified"),
        (BehaviourVerificationStatus.DIVERGED, "verified", "behaviour_diverged"),
        (BehaviourVerificationStatus.REEXECUTION_ERROR, "verified", "reexecution_error"),
        (BehaviourVerificationStatus.UNAVAILABLE, "mismatch", "provenance_mismatch"),
        (BehaviourVerificationStatus.UNAVAILABLE, "unavailable", "replay_unavailable"),
        (None, "unavailable", "integrity_valid"),
    ],
)
def test_replay_outcome_statuses_are_distinct(
    behaviour: BehaviourVerificationStatus | None, provenance: Provenance, expected: str
) -> None:
    assert _report(behaviour, provenance).status == expected


@pytest.mark.parametrize(
    "bad", ["", "../etc", "a/b", "a\\b", ".hidden", "x" * 129, "id with space"]
)
def test_scenario_id_rejects_path_unsafe_values(bad: str) -> None:
    with pytest.raises(ValidationError):
        ScenarioIdentifier(id=bad)


def test_scenario_id_accepts_packaged_ids() -> None:
    for path in Path("resources/scenarios").rglob("*.json"):
        ScenarioIdentifier.model_validate(json.loads(path.read_bytes())["scenario_id"])


def test_run_id_depends_on_scenario_content(tmp_path: Path) -> None:
    loaded = ScenarioLoader().load_from_path(SCENARIO)
    changed_trajectory = loaded.scenario.trajectory.model_copy(update={"description": "other"})
    changed = loaded.scenario.model_copy(update={"trajectory": changed_trajectory})
    runner = ScenarioRunner()
    first = asyncio.run(runner.run(loaded, output_dir=tmp_path))
    again = asyncio.run(runner.run(loaded, output_dir=tmp_path))
    other = asyncio.run(runner.run(changed, output_dir=tmp_path))
    assert first.run_id == again.run_id  # deterministic
    assert first.run_id != other.run_id  # different content never overwrites
    assert len(list(tmp_path.glob("*.bundle.json"))) == 2


def test_loader_rejects_oversized_file_before_reading(tmp_path: Path) -> None:
    big = tmp_path / "big.json"
    big.write_bytes(b" " * 64)
    with pytest.raises(ScenarioLoaderError, match="too large"):
        ScenarioLoader(max_bytes=16).load_from_path(big)

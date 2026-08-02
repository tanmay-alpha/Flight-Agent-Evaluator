"""End-to-end determinism tests for the Phase 2 runtime."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.replay.engine import ReplayEngine

SCENARIO_PATH = Path("resources/scenarios/jfk-lhr-delay.json")


@pytest.fixture
def loaded_scenario() -> BenchmarkScenario:
    loader = ScenarioLoader()
    loaded = loader.load_from_path(SCENARIO_PATH)
    return loaded.scenario


def test_full_pipeline_determinism(tmp_path: Path, loaded_scenario: BenchmarkScenario):
    """Two identical runs must produce identical recordings."""
    runner1 = ScenarioRunner()
    runner2 = ScenarioRunner()
    loader = ScenarioLoader()
    loaded = loader.load_from_path(SCENARIO_PATH)

    rec1 = asyncio.run(runner1.run(loaded, output_dir=tmp_path / "run1"))
    rec2 = asyncio.run(runner2.run(loaded, output_dir=tmp_path / "run2"))
    assert rec1.final_digest == rec2.final_digest


def test_cli_run_succeeds(tmp_path: Path):
    """The CLI run command completes without error."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flight_agent_evaluator.cli.main",
            "run",
            str(SCENARIO_PATH),
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,  # trusted: this script is built locally for tests
    )
    assert result.returncode == 0, result.stderr
    assert "Run complete" in result.stdout


def test_cli_replay(tmp_path: Path):
    """The CLI replay command completes without error."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flight_agent_evaluator.cli.main",
            "run",
            str(SCENARIO_PATH),
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,  # trusted local CLI
    )
    assert result.returncode == 0, result.stderr
    run_id = None
    for line in result.stdout.splitlines():
        if line.startswith("Run complete:"):
            run_id = line.split(":")[1].strip()
            break
    assert run_id, "No run_id found in CLI output"
    replay = subprocess.run(
        [
            sys.executable,
            "-m",
            "flight_agent_evaluator.cli.main",
            "replay",
            run_id,
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,  # trusted local CLI
    )
    assert replay.returncode == 0, replay.stderr
    assert "Replay of" in replay.stdout


def test_cli_verify_passes():
    """The CLI verify command passes for a valid run."""
    runner = ScenarioRunner()
    loaded = ScenarioLoader().load_from_path(SCENARIO_PATH)
    recording = asyncio.run(runner.run(loaded, output_dir=Path(".recordings")))
    engine = ReplayEngine(root=Path(".recordings"))
    report = engine.verify(str(recording.run_id))
    assert report.status == "verified"
    assert len(report.divergences) == 0


def test_replay_tampered_detected():
    """Verification mode must detect tampering."""
    runner = ScenarioRunner()
    loaded = ScenarioLoader().load_from_path(SCENARIO_PATH)
    recording = asyncio.run(runner.run(loaded, output_dir=Path(".recordings")))
    journal_path = Path(".recordings") / f"{recording.run_id}.jsonl"
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    # Tamper with the first entry.
    first = json.loads(lines[0])
    first["payload"] = {"x": 999}
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine = ReplayEngine(root=Path(".recordings"))
    from flight_agent_evaluator.recording.journal import JournalVerificationError

    try:
        report = engine.verify(str(recording.run_id))
    except JournalVerificationError:
        report = None
    assert report is None or report.status == "tampered"

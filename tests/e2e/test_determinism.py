"""End-to-end determinism tests for the Phase 2 runtime."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.runner import ScenarioRunner
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.evaluation.assertions import AssertionEvaluator
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.replay.engine import ReplayEngine
from flight_agent_evaluator.runtime.clock import VirtualClock
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import ToolRegistry
from flight_agent_evaluator.tools.flight import register_default_tools


SCENARIO_PATH = Path("resources/scenarios/jfk-lhr-delay.json")


@pytest.fixture
def loaded_scenario(tmp_path: Path) -> BenchmarkScenario:
    loader = ScenarioLoader()
    loaded = loader.load_from_path(SCENARIO_PATH)
    return loaded.scenario


def test_full_pipeline_determinism(tmp_path: Path, loaded_scenario: BenchmarkScenario):
    """Two identical runs must produce identical recordings."""
    clock = VirtualClock()
    registry = register_default_tools()
    from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver

    driver = ScriptedAgentDriver()
    store1 = FileRecordingStore(tmp_path / "run1")
    store2 = FileRecordingStore(tmp_path / "run2")
    id_factory1 = DeterministicIdFactory(
        scenario_id=loaded_scenario.scenario_id.id,
        scenario_version=loaded_scenario.scenario_id.version,
        seed=loaded_scenario.seed,
    )
    id_factory2 = DeterministicIdFactory(
        scenario_id=loaded_scenario.scenario_id.id,
        scenario_version=loaded_scenario.scenario_id.version,
        seed=loaded_scenario.seed,
    )
    runner1 = ScenarioRunner(
        clock=VirtualClock(), id_factory=id_factory1,
        tool_registry=registry, driver=driver, store=store1,
    )
    runner2 = ScenarioRunner(
        clock=VirtualClock(), id_factory=id_factory2,
        tool_registry=registry, driver=driver, store=store2,
    )
    from flight_agent_evaluator.engine.scenario_loader import LoadedScenario

    loaded = LoadedScenario(
        scenario=loaded_scenario,
        digest=hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest(),
        raw_bytes=SCENARIO_PATH.read_bytes(),
    )
    rec1 = runner1.run(loaded)
    rec2 = runner2.run(loaded)
    assert rec1.final_digest == rec2.final_digest


def test_cli_run_succeeds(tmp_path: Path):
    """The CLI run command completes without error."""
    result = subprocess.run(
        [sys.executable, "-m", "flight_agent_evaluator.cli.main",
         "run", str(SCENARIO_PATH), "--output", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Run complete" in result.stdout


def test_cli_replay(tmp_path: Path):
    """The CLI replay command completes without error."""
    result = subprocess.run(
        [sys.executable, "-m", "flight_agent_evaluator.cli.main",
         "run", str(SCENARIO_PATH), "--output", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    run_id = None
    for line in result.stdout.splitlines():
        if line.startswith("Run complete:"):
            run_id = line.split(":")[1].strip()
            break
    assert run_id, "No run_id found in CLI output"
    replay = subprocess.run(
        [sys.executable, "-m", "flight_agent_evaluator.cli.main",
         "replay", run_id],
        capture_output=True, text=True,
    )
    assert replay.returncode == 0, replay.stderr
    assert "Replay of" in replay.stdout


def test_cli_verify_passes():
    """The CLI verify command passes for a valid run."""
    # We create a run via the runner and then verify it.
    scenario = ScenarioLoader().load_from_path(SCENARIO_PATH).scenario
    clock = VirtualClock()
    registry = register_default_tools()
    from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver

    driver = ScriptedAgentDriver()
    store = FileRecordingStore(Path(".recordings"))
    id_factory = DeterministicIdFactory(
        scenario_id=scenario.scenario_id.id,
        scenario_version=scenario.scenario_id.version,
        seed=scenario.seed,
    )
    runner = ScenarioRunner(
        clock=clock, id_factory=id_factory,
        tool_registry=registry, driver=driver, store=store,
    )
    from flight_agent_evaluator.engine.scenario_loader import LoadedScenario
    from datetime import UTC, datetime

    loaded = LoadedScenario(
        scenario=scenario,
        digest=hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest(),
        raw_bytes=SCENARIO_PATH.read_bytes(),
    )
    recording = runner.run(loaded)
    engine = ReplayEngine(root=Path(".recordings"))
    report = engine.verify(recording.run_id)
    assert report.status == "verified"
    assert len(report.divergences) == 0


def test_replay_tampered_detected():
    """Verification mode must detect tampering."""
    # Run to create a recording.
    scenario = ScenarioLoader().load_from_path(SCENARIO_PATH).scenario
    registry = register_default_tools()
    from flight_agent_evaluator.drivers.scripted import ScriptedAgentDriver

    driver = ScriptedAgentDriver()
    store = FileRecordingStore(Path(".recordings"))
    id_factory = DeterministicIdFactory(
        scenario_id=scenario.scenario_id.id,
        scenario_version=scenario.scenario_id.version,
        seed=scenario.seed,
    )
    runner = ScenarioRunner(
        clock=VirtualClock(), id_factory=id_factory,
        tool_registry=registry, driver=driver, store=store,
    )
    from flight_agent_evaluator.engine.scenario_loader import LoadedScenario

    loaded = LoadedScenario(
        scenario=scenario,
        digest=hashlib.sha256(SCENARIO_PATH.read_bytes()).hexdigest(),
        raw_bytes=SCENARIO_PATH.read_bytes(),
    )
    recording = runner.run(loaded)
    journal_path = Path(".recordings") / f"{recording.run_id}.jsonl"
    lines = journal_path.read_text(encoding="utf-8").splitlines()
    # Tamper with the first entry.
    first = json.loads(lines[0])
    first["payload"] = {"x": 999}
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine = ReplayEngine(root=Path(".recordings"))
    report = engine.verify(recording.run_id)
    assert report.status == "tampered"
    assert len(report.divergences) > 0

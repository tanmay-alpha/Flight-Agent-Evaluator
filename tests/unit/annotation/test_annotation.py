"""Unit tests for annotation package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flight_agent_evaluator.annotation.bundle import (
    create_bundle_from_packages,
    freeze_bundle,
    verify_bundle_digest,
)
from flight_agent_evaluator.annotation.contracts import AnnotationBundle, AnnotationTaskStatus
from flight_agent_evaluator.cli.main import main as cli_main
from flight_agent_evaluator.judges.evidence import build_evidence_package

SHIPPED_BUNDLE = (
    Path(__file__).resolve().parents[3] / "validation" / "annotation-bundle-v1" / "bundle.json"
)


def test_shipped_bundle_is_declared_an_unannotated_template() -> None:
    bundle = AnnotationBundle.model_validate_json(SHIPPED_BUNDLE.read_text(encoding="utf-8"))

    assert verify_bundle_digest(bundle)
    # Its tasks carry placeholder responses, not real agent outputs, and nobody annotated them.
    assert all(task.final_response.startswith("[Synthetic") for task in bundle.tasks)
    assert all(task.annotation_count == 0 for task in bundle.tasks)
    assert all(task.status is AnnotationTaskStatus.PENDING for task in bundle.tasks)
    assert bundle.annotation_status == "template"
    note = bundle.calibration_note.lower()
    assert "template" in note
    assert "placeholder" in note
    assert "0 annotations" in note


def test_annotation_validate_cli_accepts_shipped_template(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli_main(["annotation", "validate", str(SHIPPED_BUNDLE), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["status"] == "template"
    assert payload["tasks"] == 12


def test_annotation_bundle_creation_and_freeze() -> None:
    pkg1 = build_evidence_package(
        scenario_id="scenario-1",
        run_id="run-real-123",
        public_task="Find flight to LHR",
        final_response="Found flight BA178",
    )
    pkg2 = build_evidence_package(
        scenario_id="scenario-2",
        run_id="run-real-456",
        public_task="Search alternatives",
        final_response="Found 3 options",
    )

    bundle = create_bundle_from_packages([pkg1, pkg2])

    assert len(bundle.tasks) == 2
    assert bundle.frozen is False
    assert verify_bundle_digest(bundle) is True

    # Check pseudonymisation
    assert bundle.tasks[0].pseudonymous_run_id != "run-real-123"
    assert bundle.tasks[1].pseudonymous_run_id != "run-real-456"

    # Freeze bundle
    frozen = freeze_bundle(bundle)
    assert frozen.frozen is True
    assert verify_bundle_digest(frozen) is True
    assert frozen.pending_count == 2
    assert frozen.complete_count == 0

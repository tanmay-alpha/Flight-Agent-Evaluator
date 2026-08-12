"""Unit tests for annotation package."""

from __future__ import annotations

from flight_agent_evaluator.annotation.bundle import (
    create_bundle_from_packages,
    freeze_bundle,
    verify_bundle_digest,
)
from flight_agent_evaluator.judges.evidence import build_evidence_package


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

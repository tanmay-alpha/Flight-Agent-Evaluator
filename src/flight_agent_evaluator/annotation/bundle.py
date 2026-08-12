"""Annotation bundle builder."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from flight_agent_evaluator.annotation.contracts import (
    AnnotationBundle,
    AnnotationTask,
)
from flight_agent_evaluator.judges.contracts import JudgeEvidencePackage


def create_bundle_from_packages(
    packages: list[JudgeEvidencePackage],
    rubric_version: str = "judge-rubric-v1",
) -> AnnotationBundle:
    """Create an AnnotationBundle from a list of evidence packages.

    Evidence packages are pseudonymised: run_id is replaced with a
    UUID that cannot be traced back to any model identity.

    Args:
        packages: Evidence packages to include in the bundle.
        rubric_version: Rubric version for annotators.

    Returns:
        An unfrozen AnnotationBundle ready for distribution.
    """
    tasks = []
    for package in packages:
        pseudo_run_id = str(uuid.uuid4())
        trusted_obs_list = [
            {
                "evidence_id": obs.evidence_id,
                "source": obs.source,
                "description": obs.description,
                "value": obs.value,
            }
            for obs in package.trusted_observations
        ]
        tasks.append(
            AnnotationTask(
                pseudonymous_run_id=pseudo_run_id,
                scenario_id=package.scenario_id,
                public_task=package.public_task,
                tool_call_summary=package.tool_call_summary,
                trusted_observations_json=json.dumps(
                    trusted_obs_list, sort_keys=True, separators=(",", ":")
                ),
                final_response=package.final_response,
            )
        )

    bundle = AnnotationBundle(
        tasks=tasks,
        rubric_version=rubric_version,
        created_at=datetime.now(UTC),
    )
    # Compute and embed digest
    digest = bundle.compute_digest()
    return AnnotationBundle(
        bundle_id=bundle.bundle_id,
        schema_version=bundle.schema_version,
        tasks=bundle.tasks,
        rubric_version=bundle.rubric_version,
        bundle_digest=digest,
        created_at=bundle.created_at,
        frozen=False,
        annotation_status="pending",
    )


def freeze_bundle(bundle: AnnotationBundle) -> AnnotationBundle:
    """Freeze a bundle — prevents further task additions.

    Recomputes the digest on freeze to capture final state.
    """
    digest = bundle.compute_digest()
    return AnnotationBundle(
        bundle_id=bundle.bundle_id,
        schema_version=bundle.schema_version,
        tasks=bundle.tasks,
        rubric_version=bundle.rubric_version,
        bundle_digest=digest,
        created_at=bundle.created_at,
        frozen=True,
        annotation_status=bundle.annotation_status,
    )


def verify_bundle_digest(bundle: AnnotationBundle) -> bool:
    """Return True if the bundle digest is consistent with current tasks."""
    expected = bundle.compute_digest()
    return bundle.bundle_digest == expected

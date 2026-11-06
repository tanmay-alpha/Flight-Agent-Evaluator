"""Annotation bundle builder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from flight_agent_evaluator.annotation.contracts import (
    AnnotationBundle,
    AnnotationTask,
)
from flight_agent_evaluator.annotation.tasks import deterministic_task_id
from flight_agent_evaluator.judges.contracts import JudgeEvidencePackage
from flight_agent_evaluator.strict_json import load_strict_path


def create_bundle_from_packages(
    packages: list[JudgeEvidencePackage],
    rubric_version: str = "judge-rubric-v1",
) -> AnnotationBundle:
    """Create an AnnotationBundle from a list of evidence packages.

    Task and pseudonymous run identifiers are content-addressed. Re-exporting
    the same evidence never changes the annotation join key.

    Args:
        packages: Evidence packages to include in the bundle.
        rubric_version: Rubric version for annotators.

    Returns:
        An unfrozen AnnotationBundle ready for distribution.
    """
    tasks = []
    for package in packages:
        trusted_obs_list = [
            {
                "evidence_id": obs.evidence_id,
                "source": obs.source,
                "description": obs.description,
                "value": obs.value,
            }
            for obs in package.trusted_observations
        ]
        task_id = deterministic_task_id(
            package.public_task, trusted_obs_list, package.final_response
        )
        tasks.append(
            AnnotationTask(
                task_id=task_id,
                pseudonymous_run_id=task_id,
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
        bundle_id=f"bundle-{digest}",
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


def verify_bundle_digest(bundle: AnnotationBundle | Path | str) -> bool:
    """Return True if the bundle digest is consistent with current tasks."""
    if isinstance(bundle, (str, Path)):
        bundle = AnnotationBundle.model_validate(load_strict_path(Path(bundle)))
    expected = bundle.compute_digest()
    return bundle.bundle_digest == expected

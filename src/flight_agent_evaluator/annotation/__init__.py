"""Package init for the annotation package."""

from flight_agent_evaluator.annotation.bundle import (
    create_bundle_from_packages,
    freeze_bundle,
    verify_bundle_digest,
)
from flight_agent_evaluator.annotation.contracts import (
    ANNOTATION_BUNDLE_SCHEMA_VERSION,
    AnnotationBundle,
    AnnotationTask,
    AnnotationTaskStatus,
)

__all__ = [
    "ANNOTATION_BUNDLE_SCHEMA_VERSION",
    "AnnotationBundle",
    "AnnotationTask",
    "AnnotationTaskStatus",
    "create_bundle_from_packages",
    "freeze_bundle",
    "verify_bundle_digest",
]

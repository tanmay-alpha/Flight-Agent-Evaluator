"""Blinded export, validation, adjudication and evaluator/human comparison."""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from flight_agent_evaluator.agent.security import redact_secrets
from flight_agent_evaluator.annotation.records import Adjudication, Annotation
from flight_agent_evaluator.annotation.tasks import (
    ExportManifest,
    ExportTask,
    canonical_json,
    make_task,
)
from flight_agent_evaluator.strict_json import load_strict_path, loads_strict

_LABELS = ("task_completed", "unsafe_action", "misleading_claim")
_OBSERVATION_FIELDS = {"sequence", "tool_name", "arguments", "status", "result", "error"}
MISLEADING_RESPONSE_CODES = {"STATE.FALSE_SUCCESS", "STATE.UNGROUNDED_ENTITY"}


def source_cases(paths: list[Path]) -> list[dict[str, Any]]:
    """Load benchmark bundles or trace reports without treating scores as evidence."""
    cases: list[dict[str, Any]] = []
    for path in paths:
        document = load_strict_path(path / "run.json" if path.is_dir() else path)
        if not isinstance(document, dict):
            raise ValueError(f"{path.name}: expected a benchmark bundle or trace report object")
        if "case_results" in document:
            rows = document["case_results"]
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("case_results must be an array of objects")
            cases.extend(rows)
        elif isinstance(document.get("metrics"), dict):
            cases.append(document["metrics"])
        else:
            # A standalone per-case report has the same evidence projection.
            cases.append(document)
    return cases


def task_from_case(case: dict[str, Any]) -> ExportTask:
    """Whitelist trusted tool-result fields and never distribute evaluator labels."""
    required = {"public_task", "trusted_observations", "final_response"}
    if not required <= case.keys():
        raise ValueError(
            "source lacks public_task, trusted_observations or final_response; "
            "score-only legacy artifacts cannot be annotated; rerun with evidence persistence"
        )
    observations = case["trusted_observations"]
    if not isinstance(observations, list) or any(not isinstance(o, dict) for o in observations):
        raise ValueError("trusted_observations must be an array of tool-result objects")
    if any(set(observation) - _OBSERVATION_FIELDS for observation in observations):
        raise ValueError("trusted_observations contains non-tool evidence or timing metadata")
    if not isinstance(case["public_task"], str) or (
        case["final_response"] is not None and not isinstance(case["final_response"], str)
    ):
        raise ValueError("public_task must be text and final_response text or null")
    task = make_task(case["public_task"], observations, case["final_response"])
    if case.get("task_id") is not None and case["task_id"] != task.task_id:
        raise ValueError("source task_id does not match annotation evidence")
    return task


def export_tasks(
    sources: list[Path], output_dir: Path, annotator_ids: list[str], *, seed: int = 42
) -> dict[str, Any]:
    """Write one independently shuffled, verdict-free JSONL per annotator plus digests."""
    if not annotator_ids or len(set(annotator_ids)) != len(annotator_ids):
        raise ValueError("provide one or more distinct annotator IDs")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", a) for a in annotator_ids):
        raise ValueError("annotator IDs must be safe nonempty filename components")
    cases = source_cases(sources)
    tasks = {task.task_id: task for task in map(task_from_case, cases)}
    if not tasks:
        raise ValueError("no annotation tasks in source")
    for task in tasks.values():
        task_dump = task.model_dump()
        if redact_secrets(task_dump) != task_dump:
            raise ValueError(
                f"Refusing to export task {task.task_id}: payload contains unredacted secrets"
            )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError("annotation output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for annotator in sorted(annotator_ids):
        ordered = sorted(tasks)
        rng = random.Random(f"{seed}:{annotator}")  # noqa: S311 -- reproducible blinding
        rng.shuffle(ordered)
        filename = f"{annotator}.jsonl"
        raw_text = "".join(
            canonical_json({"annotator_id": annotator, **tasks[task_id].model_dump()}) + "\n"
            for task_id in ordered
        )
        if redact_secrets(raw_text) != raw_text:
            raise ValueError(f"Refusing to write {filename}: payload contains unredacted secrets")
        raw = raw_text.encode("utf-8")
        (output_dir / filename).write_bytes(raw)
        files[filename] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema_version": "annotation-export-v1",
        "rubric_version": "judge-rubric-v1",
        "seed": seed,
        "annotators": sorted(annotator_ids),
        "source_cases": len(cases),
        "tasks": len(tasks),
        "files": files,
        "task_digests": {
            task_id: hashlib.sha256(canonical_json(task.model_dump()).encode("utf-8")).hexdigest()
            for task_id, task in sorted(tasks.items())
        },
    }
    manifest["manifest_digest"] = hashlib.sha256(
        canonical_json(manifest).encode("utf-8")
    ).hexdigest()
    manifest_text = canonical_json(manifest) + "\n"
    if redact_secrets(manifest_text) != manifest_text:
        raise ValueError("Refusing to write manifest.json: payload contains unredacted secrets")
    (output_dir / "manifest.json").write_bytes(manifest_text.encode("utf-8"))
    return manifest


def validate_export(directory: Path) -> dict[str, Any]:
    """Verify manifest, file bytes, task content addresses and complete assignment coverage."""
    manifest = load_strict_path(directory / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "annotation-export-v1":
        raise ValueError("unsupported annotation export manifest")
    manifest = ExportManifest.model_validate(manifest).model_dump()
    content = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if (
        manifest.get("manifest_digest")
        != hashlib.sha256(canonical_json(content).encode()).hexdigest()
    ):
        raise ValueError("manifest digest mismatch")
    annotators = manifest["annotators"]
    if (
        not isinstance(annotators, list)
        or not annotators
        or len(set(annotators)) != len(annotators)
    ):
        raise ValueError("invalid manifest annotators")
    if set(manifest["files"]) != {f"{a}.jsonl" for a in annotators}:
        raise ValueError("manifest file/annotator mismatch")
    for filename, digest in sorted(manifest["files"].items()):
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise ValueError("invalid export filename")
        raw = (directory / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"file digest mismatch: {filename}")
        seen = set()
        for line in raw.splitlines():
            row = loads_strict(line, source=filename)
            if not isinstance(row, dict) or row.get("annotator_id") != filename[:-6]:
                raise ValueError("assignment annotator mismatch")
            task = ExportTask.model_validate({k: v for k, v in row.items() if k != "annotator_id"})
            if task.task_id in seen:
                raise ValueError("duplicate assigned task")
            seen.add(task.task_id)
            task_digest = hashlib.sha256(canonical_json(task.model_dump()).encode()).hexdigest()
            if manifest["task_digests"].get(task.task_id) != task_digest:
                raise ValueError("task digest mismatch")
        if seen != set(manifest["task_digests"]) or len(seen) != manifest["tasks"]:
            raise ValueError("incomplete annotator assignment")
    return manifest


def validate_annotations(
    annotations: list[Annotation], export_dir: Path | None = None
) -> dict[str, Any]:
    """Validate submission membership without inventing missing labels."""
    seen = set()
    manifest = validate_export(export_dir) if export_dir else None
    for annotation in annotations:
        key = (annotation.annotator_id, annotation.task_id)
        if key in seen:
            raise ValueError("duplicate annotator/task pair")
        seen.add(key)
        if manifest and (
            annotation.annotator_id not in manifest["annotators"]
            or annotation.task_id not in manifest["task_digests"]
        ):
            raise ValueError("annotation is not assigned in this export")
    expected = manifest["tasks"] * len(manifest["annotators"]) if manifest else None
    return {
        "schema_version": "annotation-validation-v1",
        "valid": True,
        "annotations": len(annotations),
        "expected_annotations": expected,
        "missing_annotations": expected - len(annotations) if expected is not None else None,
        "status": "complete"
        if expected is not None and len(annotations) == expected
        else "incomplete",
    }


def adjudication_report(
    annotations: list[Annotation], adjudications: list[Adjudication] | None = None
) -> dict[str, Any]:
    """List every disagreement and explicit resolution; never generate final labels."""
    validate_annotations(annotations)
    by_task: dict[str, list[Annotation]] = defaultdict(list)
    for annotation in annotations:
        by_task[annotation.task_id].append(annotation)
    resolved: dict[str, Adjudication] = {}
    for adjudication in adjudications or []:
        if adjudication.task_id in resolved:
            raise ValueError("duplicate adjudication task")
        if adjudication.task_id not in by_task:
            raise ValueError("adjudication references an unknown task")
        resolved[adjudication.task_id] = adjudication
    tasks = []
    for task_id, group in sorted(by_task.items()):
        rows = sorted(group, key=lambda a: a.annotator_id)
        fields = {}
        for criterion in rows[0].scores.model_dump():
            values = {a.annotator_id: getattr(a.scores, criterion) for a in rows}
            if len(set(values.values())) > 1:
                fields[f"scores.{criterion}"] = values
        for label in _LABELS:
            values = {a.annotator_id: getattr(a, label) for a in rows}
            if len(set(values.values())) > 1:
                fields[label] = values
        resolution = resolved.get(task_id)
        tasks.append(
            {
                "task_id": task_id,
                "annotators": [a.annotator_id for a in rows],
                "status": "adjudicated"
                if resolution
                else (
                    "disagreement"
                    if fields
                    else "agreement"
                    if len(rows) >= 2
                    else "insufficient_data"
                ),
                "disagreements": fields,
                "adjudication": resolution.model_dump() if resolution else None,
            }
        )
    unresolved = sum(t["status"] == "disagreement" for t in tasks)
    return {
        "schema_version": "annotation-adjudication-report-v1",
        "status": "unresolved"
        if unresolved
        else "insufficient_data"
        if not tasks or any(t["status"] == "insufficient_data" for t in tasks)
        else "complete",
        "disagreement_tasks": sum(bool(t["disagreements"]) for t in tasks),
        "unresolved_tasks": unresolved,
        "tasks": tasks,
    }


def wilson_interval(successes: int, total: int) -> dict[str, Any]:
    """Binomial Wilson score interval at 95%; zero denominators are not zero scores."""
    if total == 0:
        return {
            "status": "insufficient_data",
            "value": None,
            "ci95": None,
            "numerator": successes,
            "denominator": total,
        }
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {
        "status": "ok",
        "value": p,
        "ci95": [max(0.0, center - half), min(1.0, center + half)],
        "numerator": successes,
        "denominator": total,
    }


def compare_evaluator(
    cases: list[dict[str, Any]],
    annotations: list[Annotation],
    adjudications: list[Adjudication] | None = None,
) -> dict[str, Any]:
    """Join on task_id using adjudication or unanimous labels from >=2 annotators.

    Task failure = not task_success; safety violation = not safety_pass; misleading
    claim = failure code in MISLEADING_RESPONSE_CODES. Evaluator errors and unclear/unresolved labels are
    excluded with counts. Identical-content repeats count once, not as independent labels.
    """
    adjudication_report(annotations, adjudications)
    grouped: dict[str, list[Annotation]] = defaultdict(list)
    for annotation in annotations:
        grouped[annotation.task_id].append(annotation)
    resolutions = {a.task_id: a.final_labels for a in adjudications or []}
    predictions: dict[str, dict[str, Any]] = {}
    duplicate_cases = 0
    for case in cases:
        task_id = case.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(
                "evaluator case lacks task_id; score-only legacy artifacts cannot be joined"
            )
        if case.get("evaluator_status") == "evaluator_error":
            prediction = {"evaluator_error": True}
        else:
            if (
                type(case.get("task_success")) is not bool
                or type(case.get("safety_pass")) is not bool
            ):
                raise ValueError("case task_success and safety_pass must be booleans")
            if not isinstance(case.get("failure_codes"), list) or any(
                not isinstance(c, str) for c in case["failure_codes"]
            ):
                raise ValueError("case failure_codes must be an array of strings")
            prediction = {
                "task_failure": not case["task_success"],
                "safety_violation": not case["safety_pass"],
                "misleading_claim": bool(set(case["failure_codes"]) & MISLEADING_RESPONSE_CODES),
            }
        if task_id in predictions:
            if prediction != predictions[task_id]:
                raise ValueError("conflicting evaluator predictions for identical task_id")
            duplicate_cases += 1
        predictions[task_id] = prediction
    metrics = {}
    for metric, label in (
        ("task_failure", "task_completed"),
        ("safety_violation", "unsafe_action"),
        ("misleading_claim", "misleading_claim"),
    ):
        counts = dict.fromkeys(
            ("true_positive", "false_positive", "false_negative", "true_negative"), 0
        )
        excluded = dict.fromkeys(
            ("unmatched", "evaluator_error", "unclear", "unresolved", "insufficient_annotators"), 0
        )
        for task_id, prediction in sorted(predictions.items()):
            group = grouped.get(task_id, [])
            if prediction.get("evaluator_error"):
                excluded["evaluator_error"] += 1
                continue
            if task_id in resolutions:
                truth = getattr(resolutions[task_id], label)
            elif not group:
                excluded["unmatched"] += 1
                continue
            elif len(group) < 2:
                excluded["insufficient_annotators"] += 1
                continue
            else:
                values = {getattr(a, label) for a in group}
                if len(values) > 1:
                    excluded["unresolved"] += 1
                    continue
                truth = next(iter(values))
            if truth == "unclear":
                excluded["unclear"] += 1
                continue
            positive = truth == ("no" if metric == "task_failure" else "yes")
            key = (
                ("true_positive" if positive else "false_positive")
                if prediction[metric]
                else ("false_negative" if positive else "true_negative")
            )
            counts[key] += 1
        tp = counts["true_positive"]
        metrics[metric] = {
            "status": "ok" if sum(counts.values()) else "insufficient_data",
            "counts": counts,
            "excluded": excluded,
            "precision": wilson_interval(tp, tp + counts["false_positive"]),
            "recall": wilson_interval(tp, tp + counts["false_negative"]),
        }
    return {
        "schema_version": "annotation-evaluator-comparison-v1",
        "status": "ok"
        if any(m["status"] == "ok" for m in metrics.values())
        else "insufficient_data",
        "source_cases": len(cases),
        "unique_tasks": len(predictions),
        "duplicate_content_cases": duplicate_cases,
        "human_tasks_without_case": len((set(grouped) | set(resolutions)) - predictions.keys()),
        "misleading_claim_detector": sorted(MISLEADING_RESPONSE_CODES),
        "metrics": metrics,
    }

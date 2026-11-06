"""Consumer-visible export, strict-schema, adjudication and comparison regressions."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from pydantic import ValidationError

from flight_agent_evaluator.agent.baselines import ScriptedOracleAgent
from flight_agent_evaluator.annotation.bundle import (
    create_bundle_from_packages,
    verify_bundle_digest,
)
from flight_agent_evaluator.annotation.cli import main, render_markdown
from flight_agent_evaluator.annotation.records import (
    Adjudication,
    Annotation,
    CriterionScores,
    Labels,
    load_records,
)
from flight_agent_evaluator.annotation.tasks import canonical_json, deterministic_task_id, make_task
from flight_agent_evaluator.annotation.workflow import (
    adjudication_report,
    compare_evaluator,
    export_tasks,
    source_cases,
    task_from_case,
    validate_annotations,
    validate_export,
    wilson_interval,
)
from flight_agent_evaluator.contracts.trajectory_expectation import load_builtin_expectation
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.judges.evidence import build_evidence_package
from flight_agent_evaluator.recording.store import FileRecordingStore
from flight_agent_evaluator.strict_json import StrictJSONError


@pytest.fixture
def annotation_factory():
    def make(task_id="task-1", annotator_id="synthetic-test-a", score=2, **kwargs):
        return Annotation.model_validate(
            {
                "annotator_id": annotator_id,
                "task_id": task_id,
                "scores": dict.fromkeys(CriterionScores.model_fields, score),
                "rationale": "Test-only assessment.",
                "task_completed": "yes",
                "unsafe_action": "no",
                "misleading_claim": "no",
                **kwargs,
            }
        )

    return make


def _case(index=0, **kwargs):
    task = make_task(
        f"Request {index}",
        [
            {
                "sequence": 2,
                "tool_name": "flight.get_status",
                "status": "success",
                "result": {"status": "delayed"},
            }
        ],
        f"Response {index}",
    )
    return {
        **task.model_dump(),
        "task_success": True,
        "safety_pass": True,
        "failure_codes": [],
        "agent_id": "do-not-export-model",
        "overall_score": 1.0,
        **kwargs,
    }


def _write_json(path, content):
    path.write_text(canonical_json(content), encoding="utf-8")
    return path


def test_package_tasks_and_digests_are_deterministic():
    package = build_evidence_package(
        scenario_id="scenario",
        run_id="private-model-run",
        public_task="Request",
        final_response="Answer",
    )
    one = create_bundle_from_packages([package])
    two = create_bundle_from_packages([package])
    assert one.tasks == two.tasks
    assert one.bundle_digest == two.bundle_digest
    assert one.bundle_id == two.bundle_id
    assert "private-model-run" not in one.model_dump_json()


def test_bundle_verification_rejects_duplicate_json_keys(tmp_path):
    package = build_evidence_package(
        scenario_id="scenario", run_id="run", public_task="Request", final_response="Answer"
    )
    bundle = create_bundle_from_packages([package])
    path = tmp_path / "bundle.json"
    path.write_text('{"bundle_digest":"ignored",' + bundle.model_dump_json()[1:], encoding="utf-8")
    with pytest.raises(StrictJSONError, match="duplicate"):
        verify_bundle_digest(path)


def test_export_blinds_and_shuffles_each_annotator_deterministically(tmp_path):
    cases = [_case(i) for i in range(20)]
    source = _write_json(tmp_path / "run.json", {"case_results": cases + [cases[0]]})
    manifest = export_tasks(
        [source], tmp_path / "one", ["synthetic-test-a", "synthetic-test-b"], seed=9
    )
    same = export_tasks(
        [source], tmp_path / "two", ["synthetic-test-b", "synthetic-test-a"], seed=9
    )
    assert manifest == same
    assert manifest["source_cases"] == 21 and manifest["tasks"] == 20
    assert validate_export(tmp_path / "one") == manifest
    a = (tmp_path / "one" / "synthetic-test-a.jsonl").read_bytes()
    b = (tmp_path / "one" / "synthetic-test-b.jsonl").read_bytes()
    assert [json.loads(line)["task_id"] for line in a.splitlines()] != [
        json.loads(line)["task_id"] for line in b.splitlines()
    ]
    for raw in (a, b):
        assert b"do-not-export-model" not in raw and b"task_success" not in raw
        assert b"overall_score" not in raw and b"failure_codes" not in raw
        assert b"delayed" in raw
    assert a == (tmp_path / "two" / "synthetic-test-a.jsonl").read_bytes()
    changed = export_tasks([source], tmp_path / "three", ["synthetic-test-a"], seed=10)
    assert changed["task_digests"] == manifest["task_digests"]
    assert changed["files"] != {
        "synthetic-test-a.jsonl": manifest["files"]["synthetic-test-a.jsonl"]
    }


def test_export_consumes_scripted_agent_recording_in_tmp_bundle(tmp_path):
    scenario = ScenarioLoader().load_builtin("scenarios/jfk-lhr-delay.json").scenario
    metrics = asyncio.run(
        BenchmarkRunner().run_scenario(
            scenario,
            ScriptedOracleAgent(),
            expectation=load_builtin_expectation("expectations/jfk-lhr-delay.json"),
            output_dir=tmp_path / "recordings",
            scenario_source_digest="a" * 64,
        )
    )
    assert metrics.run_id
    journal, recording, _ = FileRecordingStore(tmp_path / "recordings").read_bundle(metrics.run_id)
    # Persist only authenticated tool results, not the imported trace's claimed outputs.
    observations = [
        {
            "sequence": entry.seq,
            **{
                key: value
                for key, value in entry.payload.items()
                if key in {"status", "result", "error"}
            },
        }
        for entry in journal.entries
        if entry.type == "tool_result"
    ]
    assert observations
    public_task = scenario.steps[0].initial_message or scenario.steps[0].description
    task = make_task(public_task, observations, recording.final_response)
    bundle = tmp_path / "benchmark"
    bundle.mkdir()
    _write_json(
        bundle / "run.json",
        {"case_results": [{**task.model_dump(), "task_success": metrics.task_success}]},
    )
    manifest = export_tasks([bundle], tmp_path / "export", ["synthetic-test-a"])
    assert manifest["tasks"] == 1
    row = json.loads((tmp_path / "export" / "synthetic-test-a.jsonl").read_text())
    assert row["final_response"] == recording.final_response
    assert row["trusted_observations"] == observations
    assert row["public_task"] == public_task


def test_trace_report_export_uses_environment_metrics_not_claimed_outputs(tmp_path):
    case = _case()
    source = _write_json(
        tmp_path / "report.json",
        {"agent": {"model": "private"}, "observed_result": "FAKE", "metrics": case},
    )
    assert source_cases([source]) == [case]
    result = export_tasks([source], tmp_path / "export", ["synthetic-test-a"])
    assert result["tasks"] == 1
    assert "FAKE" not in (tmp_path / "export" / "synthetic-test-a.jsonl").read_text()


@pytest.mark.parametrize(
    "case, message",
    [
        ({"task_success": True}, "lacks"),
        (_case(trusted_observations=[{"safety_passed": True}]), "non-tool"),
        (_case(trusted_observations={}), "array"),
        (_case(public_task=1), "text"),
        (_case(final_response=False), "text"),
        (_case(task_id="wrong"), "task_id"),
    ],
)
def test_task_export_rejects_untrustworthy_or_incomplete_sources(case, message):
    with pytest.raises(ValueError, match=message):
        task_from_case(case)


@pytest.mark.parametrize("annotators", [[], ["same", "same"], ["../escape"], ["a/b"], ["a\\b"]])
def test_export_rejects_invalid_assignments(tmp_path, annotators):
    with pytest.raises(ValueError):
        export_tasks([], tmp_path / "export", annotators)


def test_export_refuses_empty_sources_and_overwrite(tmp_path):
    empty = _write_json(tmp_path / "empty.json", {"case_results": []})
    with pytest.raises(ValueError, match="no annotation"):
        export_tasks([empty], tmp_path / "export", ["a"])
    source = _write_json(tmp_path / "run.json", {"case_results": [_case()]})
    export_tasks([source], tmp_path / "export", ["a"])
    with pytest.raises(FileExistsError):
        export_tasks([source], tmp_path / "export", ["a"])
    (tmp_path / "export" / "a.jsonl").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="file digest"):
        validate_export(tmp_path / "export")


@pytest.mark.parametrize("document", [[], {"case_results": {}}, {"case_results": [1]}])
def test_source_cases_rejects_invalid_shapes(tmp_path, document):
    with pytest.raises(ValueError):
        source_cases([_write_json(tmp_path / "source.json", document)])


@pytest.mark.parametrize("score", [True, False, -1, 5, 1.5, "2", None])
def test_scores_are_strict_not_coerced(annotation_factory, score):
    with pytest.raises(ValidationError):
        annotation_factory(score=score)


def test_annotation_schema_requires_complete_scores_and_explicit_binary_labels(annotation_factory):
    annotation = annotation_factory(
        score="cannot_judge", task_completed="unclear", time_spent_seconds=2.5
    )
    assert annotation.scores.groundedness == "cannot_judge"
    for change in (
        {"unexpected": 1},
        {"scores": {"clarity": 2}},
        {"unsafe_action": True},
        {"rationale": " "},
        {"time_spent_seconds": -1},
        {"time_spent_seconds": float("inf")},
    ):
        with pytest.raises(ValidationError):
            annotation_factory(**change)


def test_jsonl_loader_strictness_and_duplicate_submissions(tmp_path, annotation_factory):
    annotation = annotation_factory()
    path = tmp_path / "labels.jsonl"
    path.write_text(annotation.model_dump_json() + "\n", encoding="utf-8")
    assert load_records([path], Annotation) == [annotation]
    with pytest.raises(ValueError, match="duplicate"):
        load_records([path, path], Annotation)
    for raw in (
        '{"annotator_id":"a","annotator_id":"b"}',
        '{"time_spent_seconds":NaN}',
        "\ufeff{}",
        "{}\n\n",
    ):
        path.write_text(raw, encoding="utf-8")
        with pytest.raises((StrictJSONError, ValidationError)):
            load_records([path], Annotation)


def test_assignment_membership_and_missing_annotation_counts(tmp_path, annotation_factory):
    source = _write_json(tmp_path / "run.json", {"case_results": [_case()]})
    export_tasks([source], tmp_path / "export", ["synthetic-test-a", "synthetic-test-b"])
    annotation = annotation_factory(task_id=_case()["task_id"])
    report = validate_annotations([annotation], tmp_path / "export")
    assert report["missing_annotations"] == 1 and report["status"] == "incomplete"
    assert (
        validate_annotations(
            [
                annotation,
                annotation_factory(task_id=annotation.task_id, annotator_id="synthetic-test-b"),
            ],
            tmp_path / "export",
        )["status"]
        == "complete"
    )
    with pytest.raises(ValueError, match="not assigned"):
        validate_annotations([annotation_factory()], tmp_path / "export")
    with pytest.raises(ValueError, match="duplicate"):
        validate_annotations([annotation, annotation])


def test_disagreements_require_explicit_adjudication(annotation_factory):
    one = annotation_factory()
    two = annotation_factory(annotator_id="synthetic-test-b", score=3, unsafe_action="yes")
    report = adjudication_report([one, two])
    assert report["status"] == "unresolved"
    assert len(report["tasks"][0]["disagreements"]) == 7
    resolution = Adjudication(
        adjudicator_id="reviewer",
        task_id=one.task_id,
        final_labels=Labels.model_validate(
            {
                "scores": one.scores.model_dump(),
                "task_completed": "yes",
                "unsafe_action": "no",
                "misleading_claim": "no",
            }
        ),
        reason="Verified the tool outcome.",
    )
    assert adjudication_report([one, two], [resolution])["tasks"][0]["status"] == "adjudicated"
    assert adjudication_report([])["status"] == "insufficient_data"
    assert adjudication_report([one])["tasks"][0]["status"] == "insufficient_data"
    assert (
        adjudication_report([one, annotation_factory(annotator_id="synthetic-test-b")])["tasks"][0][
            "status"
        ]
        == "agreement"
    )
    with pytest.raises(ValueError, match="duplicate"):
        adjudication_report([one], [resolution, resolution])
    with pytest.raises(ValueError, match="unknown"):
        adjudication_report([], [resolution])


def test_comparison_confusion_counts_and_wilson_intervals(annotation_factory):
    annotations: list[Annotation] = []
    cases = []
    for i, (truth, prediction) in enumerate(
        ((True, True), (False, True), (True, False), (False, False))
    ):
        cases.append(
            _case(
                i,
                task_success=not prediction,
                safety_pass=not prediction,
                failure_codes=["STATE.FALSE_SUCCESS"] if prediction else [],
            )
        )
        annotations.extend(
            annotation_factory(
                task_id=cases[-1]["task_id"],
                annotator_id=annotator,
                task_completed="no" if truth else "yes",
                unsafe_action="yes" if truth else "no",
                misleading_claim="yes" if truth else "no",
            )
            for annotator in ("synthetic-test-a", "synthetic-test-b")
        )
    report = compare_evaluator(cases + [cases[0]], annotations)
    assert report["duplicate_content_cases"] == 1
    for metric in report["metrics"].values():
        assert metric["counts"] == {
            "true_positive": 1,
            "false_positive": 1,
            "false_negative": 1,
            "true_negative": 1,
        }
        assert metric["precision"]["value"] == metric["recall"]["value"] == 0.5
        assert metric["precision"]["ci95"] == pytest.approx([0.0945312, 0.9054688])
    assert wilson_interval(0, 0)["status"] == "insufficient_data"
    assert wilson_interval(0, 1)["ci95"][0] == 0
    assert wilson_interval(1, 1)["ci95"][1] == 1


def test_comparison_exclusions_and_resolutions(annotation_factory):
    cases = [_case(i) for i in range(6)]
    cases[0]["evaluator_status"] = "evaluator_error"
    annotations = [annotation_factory(task_id=cases[2]["task_id"])]
    for i in (3, 4):
        annotations += [
            annotation_factory(task_id=cases[i]["task_id"]),
            annotation_factory(
                task_id=cases[i]["task_id"],
                annotator_id="synthetic-test-b",
                task_completed="unclear" if i == 3 else "no",
                unsafe_action="unclear" if i == 3 else "yes",
                misleading_claim="unclear" if i == 3 else "yes",
            ),
        ]
    annotations += [
        annotation_factory(
            task_id=cases[5]["task_id"],
            annotator_id=a,
            task_completed="unclear",
            unsafe_action="unclear",
            misleading_claim="unclear",
        )
        for a in ("synthetic-test-a", "synthetic-test-b")
    ]
    report = compare_evaluator(cases, annotations)
    assert report["status"] == "insufficient_data"
    assert report["metrics"]["task_failure"]["excluded"] == {
        "evaluator_error": 1,
        "unmatched": 1,
        "insufficient_annotators": 1,
        "unresolved": 2,
        "unclear": 1,
    }
    resolution = Adjudication(
        adjudicator_id="reviewer",
        task_id=cases[4]["task_id"],
        final_labels=Labels.model_validate(
            {
                "scores": annotations[0].scores.model_dump(),
                "task_completed": "yes",
                "unsafe_action": "no",
                "misleading_claim": "no",
            }
        ),
        reason="Resolved against observations.",
    )
    assert compare_evaluator(cases, annotations, [resolution])["status"] == "ok"
    assert compare_evaluator([], [annotation_factory()])["human_tasks_without_case"] == 1
    for invalid in (
        {},
        {"task_id": "id", "task_success": 1, "safety_pass": True},
        {"task_id": "id", "task_success": True, "safety_pass": True, "failure_codes": "bad"},
    ):
        with pytest.raises(ValueError):
            compare_evaluator([invalid], [])
    with pytest.raises(ValueError, match="conflicting"):
        compare_evaluator([_case(), _case(task_success=False)], [])


def test_task_hash_does_not_bind_wall_clock_or_model_identity():
    case = _case()
    task = task_from_case(case)
    assert task_from_case({**case, "wall_time_ms": 999, "agent_id": "different"}) == task
    assert task.task_id == deterministic_task_id(
        task.public_task, task.trusted_observations, task.final_response
    )
    with pytest.raises(ValidationError, match="task_id"):
        type(task).model_validate({**task.model_dump(), "public_task": "modified"})
    with pytest.raises(ValueError):
        canonical_json(float("nan"))


def test_cli_all_commands_json_markdown_and_errors(tmp_path, annotation_factory, capsys):
    case = _case()
    source = _write_json(tmp_path / "run.json", {"case_results": [case]})
    export = tmp_path / "export"
    assert (
        main(
            [
                "export",
                str(source),
                "--output",
                str(export),
                "--annotators",
                "synthetic-test-a",
                "synthetic-test-b",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["tasks"] == 1
    assert main(["validate", "--export-dir", str(export)]) == 0
    capsys.readouterr()
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        "\n".join(
            annotation_factory(task_id=case["task_id"], annotator_id=a).model_dump_json()
            for a in ("synthetic-test-a", "synthetic-test-b")
        )
        + "\n",
        encoding="utf-8",
    )
    for args in (
        ["validate", str(labels), "--export-dir", str(export)],
        ["agreement", str(labels), "--bootstrap-samples", "10"],
        ["adjudicate", str(labels)],
        ["compare-evaluator", str(source), "--annotations", str(labels)],
    ):
        assert main(args) == 0
        assert isinstance(json.loads(capsys.readouterr().out), dict)
    report_path = tmp_path / "agreement.md"
    assert (
        main(
            [
                "agreement",
                str(labels),
                "--bootstrap-samples",
                "0",
                "--format",
                "markdown",
                "--report",
                str(report_path),
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert text.startswith("# annotation-agreement-v1") and report_path.read_text() == text
    assert render_markdown({"value": 1}) == '# Annotation report\n\n```json\n{"value":1}\n```\n'
    assert main(["validate"]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "invalid"
    assert main(["agreement", str(tmp_path / "missing")]) == 2
    capsys.readouterr()


def test_manifest_tampering_fails(tmp_path):
    source = _write_json(tmp_path / "run.json", {"case_results": [_case()]})
    export_tasks([source], tmp_path / "export", ["a"])
    path = tmp_path / "export" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["tasks"] = 99
    _write_json(path, manifest)
    with pytest.raises(ValueError, match="manifest digest"):
        validate_export(tmp_path / "export")
    _write_json(path, {"schema_version": "future"})
    with pytest.raises(ValueError, match="unsupported"):
        validate_export(tmp_path / "export")


@pytest.mark.parametrize(
    "change, message",
    [
        ({"annotators": ["a", "a"]}, "annotators"),
        ({"files": {}}, "file/annotator"),
        ({"tasks": 2}, "incomplete"),
        ({"task_digests": {}}, "task digest"),
    ],
)
def test_manifest_cross_checks_even_when_digest_is_recomputed(tmp_path, change, message):
    source = _write_json(tmp_path / "run.json", {"case_results": [_case()]})
    manifest = export_tasks([source], tmp_path / "export", ["a"])
    manifest.update(change)
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    _write_json(tmp_path / "export" / "manifest.json", manifest)
    with pytest.raises(ValueError, match=message):
        validate_export(tmp_path / "export")


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("wrong-annotator", "annotator mismatch"),
        ("duplicate-task", "duplicate assigned"),
        ("wrong-task-digest", "task digest"),
    ],
)
def test_packet_cross_checks_even_when_file_digest_is_recomputed(tmp_path, mutation, message):
    source = _write_json(tmp_path / "run.json", {"case_results": [_case()]})
    manifest = export_tasks([source], tmp_path / "export", ["a"])
    packet = tmp_path / "export" / "a.jsonl"
    row = json.loads(packet.read_text())
    if mutation == "wrong-annotator":
        row["annotator_id"] = "b"
    elif mutation == "wrong-task-digest":
        manifest["task_digests"][row["task_id"]] = "0" * 64
    text = canonical_json(row) + "\n"
    if mutation == "duplicate-task":
        text *= 2
    raw = text.encode()
    packet.write_bytes(raw)
    manifest["files"]["a.jsonl"] = hashlib.sha256(raw).hexdigest()
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    _write_json(tmp_path / "export" / "manifest.json", manifest)
    with pytest.raises(ValueError, match=message):
        validate_export(tmp_path / "export")


def test_module_entrypoint_and_strict_adjudication_jsonl(
    tmp_path, monkeypatch, capsys, annotation_factory
):
    import runpy
    import sys

    annotation = annotation_factory()
    resolution = Adjudication.model_validate(
        {
            "adjudicator_id": "reviewer",
            "task_id": annotation.task_id,
            "final_labels": {
                key: value
                for key, value in annotation.model_dump().items()
                if key in {"scores", "task_completed", "unsafe_action", "misleading_claim"}
            },
            "reason": "Resolved in test only.",
        }
    )
    path = tmp_path / "resolutions.jsonl"
    path.write_text(resolution.model_dump_json() + "\n", encoding="utf-8")
    assert load_records([path], Adjudication) == [resolution]
    with pytest.raises(ValueError, match="duplicate"):
        load_records([path, path], Adjudication)
    labels = tmp_path / "labels.jsonl"
    labels.write_text(annotation.model_dump_json() + "\n", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["annotation", "adjudicate", str(labels), "--adjudications", str(path)]
    )
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("flight_agent_evaluator.annotation", run_name="__main__")
    assert caught.value.code == 0
    assert json.loads(capsys.readouterr().out)["tasks"][0]["status"] == "adjudicated"

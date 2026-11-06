"""Standalone deterministic annotation commands (no human labels are generated)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from flight_agent_evaluator.annotation.records import Adjudication, Annotation, load_records
from flight_agent_evaluator.annotation.statistics import agreement_report
from flight_agent_evaluator.annotation.tasks import canonical_json
from flight_agent_evaluator.annotation.workflow import (
    adjudication_report,
    compare_evaluator,
    export_tasks,
    source_cases,
    validate_annotations,
    validate_export,
)
from flight_agent_evaluator.recording.store import RecordingStoreError


def render_markdown(report: dict[str, Any]) -> str:
    """Render every report field, including counts and exclusions, without truncation."""
    title = report.get("schema_version", "Annotation report")
    # JSON within Markdown preserves exact labels, nested counts and interval endpoints.
    return f"# {title}\n\n```json\n{canonical_json(report)}\n```\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m flight_agent_evaluator.annotation")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser(
        "export", help="export blinded tasks from bundles or trace reports"
    )
    export.add_argument("sources", nargs="+", type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--annotators", nargs="+", required=True)
    export.add_argument("--seed", type=int, default=42)
    validate = commands.add_parser(
        "validate", help="validate JSONL annotations and optional assignments"
    )
    validate.add_argument("annotations", nargs="*", type=Path)
    validate.add_argument("--export-dir", type=Path)
    agreement = commands.add_parser("agreement", help="compute criterion and binary agreement")
    agreement.add_argument("annotations", nargs="+", type=Path)
    agreement.add_argument("--seed", type=int, default=42)
    agreement.add_argument("--bootstrap-samples", type=int, default=1000)
    adjudicate = commands.add_parser(
        "adjudicate", help="report disagreements and human resolutions"
    )
    adjudicate.add_argument("annotations", nargs="+", type=Path)
    adjudicate.add_argument("--adjudications", nargs="+", type=Path, default=[])
    compare = commands.add_parser(
        "compare-evaluator", help="compare task-id joined evaluator and human labels"
    )
    compare.add_argument("sources", nargs="+", type=Path)
    compare.add_argument("--annotations", nargs="+", type=Path, required=True)
    compare.add_argument("--adjudications", nargs="+", type=Path, default=[])
    for command in (export, validate, agreement, adjudicate, compare):
        command.add_argument("--format", choices=("json", "markdown"), default="json")
        command.add_argument("--report", type=Path, help="also write the deterministic report here")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run an annotation command; invalid data produces a deterministic nonzero report."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "export":
            report = export_tasks(args.sources, args.output, args.annotators, seed=args.seed)
        elif args.command == "validate":
            if not args.annotations and args.export_dir:
                manifest = validate_export(args.export_dir)
                report = {
                    "schema_version": "annotation-validation-v1",
                    "valid": True,
                    "tasks": manifest["tasks"],
                }
            elif not args.annotations:
                raise ValueError("validate requires annotation files or --export-dir")
            else:
                report = validate_annotations(
                    load_records(args.annotations, Annotation), args.export_dir
                )
        elif args.command == "agreement":
            report = agreement_report(
                load_records(args.annotations, Annotation),
                seed=args.seed,
                bootstrap_samples=args.bootstrap_samples,
            )
        elif args.command == "adjudicate":
            report = adjudication_report(
                load_records(args.annotations, Annotation),
                load_records(args.adjudications, Adjudication),
            )
        else:
            report = compare_evaluator(
                source_cases(args.sources),
                load_records(args.annotations, Annotation),
                load_records(args.adjudications, Adjudication),
            )
    except (OSError, ValueError, ValidationError, RecordingStoreError) as exc:
        print(canonical_json({"status": "invalid", "error": str(exc)}), file=sys.stderr)
        return 2
    text = render_markdown(report) if args.format == "markdown" else canonical_json(report) + "\n"
    if args.report:
        args.report.write_bytes(text.encode("utf-8"))
    print(text, end="")
    return 0

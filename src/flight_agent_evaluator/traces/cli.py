"""Command-line entry: ``python -m flight_agent_evaluator.traces <trace.json> [--json]``.

Exit codes: ``0`` the replayed run achieved task success and passed safety,
``1`` the evaluation ran but the run failed, ``2`` the trace or its scenario
could not be loaded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from flight_agent_evaluator.engine.scenario_loader import (
    ScenarioLoaderError,
    ScenarioVersionMismatchError,
)
from flight_agent_evaluator.resources.contracts import ResourceError
from flight_agent_evaluator.traces.evaluate import TraceEvaluationReport, evaluate_trace
from flight_agent_evaluator.traces.format import load_trace

_INPUT_ERRORS = (
    ValueError,  # TraceFormatError, TraceResolutionError, expectation load failures
    OSError,
    ResourceError,
    ScenarioLoaderError,
    ScenarioVersionMismatchError,
)

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_INPUT_ERROR = 2


class _TraceArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # noqa: ARG002
        """Do not echo untrusted argument values in parser errors."""
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT_ERROR, "error: invalid trace command-line arguments\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = _TraceArgumentParser(
        prog="python -m flight_agent_evaluator.traces",
        description=(
            "Evaluate an externally produced agent tool-call trace by re-executing it "
            "against the simulated airline environment."
        ),
    )
    parser.add_argument("trace", type=Path, help="Path to a trace JSON file.")
    parser.add_argument("--json", action="store_true", help="Emit the full report as JSON.")
    parser.add_argument(
        "--allow-root",
        type=Path,
        help="Additional root for relative scenario and expectation paths (no links or '..').",
    )
    return parser


def render_text(report: TraceEvaluationReport) -> str:
    """Human-readable summary of a trace evaluation report."""
    m = report.metrics
    agent = report.agent
    agent_desc = agent.name + "".join(
        f" {label}={value}"
        for label, value in (("model", agent.model), ("framework", agent.framework))
        if value
    )
    lines = [
        f"Scenario:        {report.scenario_id} ({report.scenario_source})",
        f"Expectation:     {report.expectation_source}",
        f"Agent:           {agent_desc}",
        f"Task success:    {m.task_success}",
        f"Safety pass:     {m.safety_pass}",
        f"Overall score:   {m.overall_score:.4f}",
        f"Tool calls:      {report.replayed_call_count} replayed / {report.trace_call_count} in trace",
        f"Failure codes:   {', '.join(m.failure_codes) or 'none'}",
        f"Journal digest:  {m.journal_digest}",
        f"Trace consistent with environment: {report.trace_consistent}",
    ]
    lines.extend(f"  - {d.as_warning()}" for d in report.divergences)
    for detail in m.failure_details:
        lines.append(f"  [{detail.severity}] {detail.code}: {detail.message}")
        lines.append(f"    Evidence sequences: {detail.evidence_sequences}")
        if detail.remediation:
            lines.append(f"    Remediation: {detail.remediation}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the trace evaluation CLI and return a process exit code."""
    args = _build_parser().parse_args(argv)
    trace_path: Path = args.trace
    try:
        trace = load_trace(trace_path)
        report = evaluate_trace(
            trace, base_dir=trace_path.absolute().parent, allow_root=args.allow_root
        )
    except _INPUT_ERRORS:
        print(
            "error: trace or referenced scenario/expectation could not be loaded", file=sys.stderr
        )
        return EXIT_INPUT_ERROR

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(render_text(report))
    passed = report.metrics.task_success and report.metrics.safety_pass
    return EXIT_PASSED if passed else EXIT_FAILED

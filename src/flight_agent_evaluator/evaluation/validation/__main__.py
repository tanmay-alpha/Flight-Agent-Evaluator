"""``python -m flight_agent_evaluator.evaluation.validation --output <dir>``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from flight_agent_evaluator.evaluation.validation import (
    render_markdown,
    report_to_canonical_json,
    run_evaluator_validation,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the evaluator validation harness and write report.json + report.md."""
    parser = argparse.ArgumentParser(
        prog="python -m flight_agent_evaluator.evaluation.validation",
        description="Measure trajectory-evaluator FP/FN rates on construction-labelled perturbations.",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output directory.")
    parser.add_argument("--benchmark", default="benchmark-v1", help="Built-in benchmark id.")
    args = parser.parse_args(argv)

    report = run_evaluator_validation(benchmark_id=args.benchmark)
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_bytes((report_to_canonical_json(report) + "\n").encode("utf-8"))
    (output / "report.md").write_bytes(render_markdown(report).encode("utf-8"))
    print(f"Wrote {output / 'report.json'} and {output / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

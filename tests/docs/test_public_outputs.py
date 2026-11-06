"""The supported SDK and CLI examples print useful, stable key output labels."""

from __future__ import annotations

import pytest

import flight_agent_evaluator as sdk
from flight_agent_evaluator.cli.main import main


def test_public_sdk_names_are_exported():
    names = {
        "evaluate_trace",
        "evaluate_trace_async",
        "load_trace",
        "parse_trace",
        "AgentPolicy",
        "BenchmarkRunner",
        "CanonicalBenchmarkEngine",
        "compare_runs",
        "TraceEvaluationReport",
        "BenchmarkRunArtifact",
        "BenchmarkCaseResult",
        "BenchmarkMetricVector",
        "RunComparisonReport",
        "FailureDetail",
        "TraceSourceMetadata",
        "TraceAssistantContent",
    }
    assert names <= set(sdk.__all__)
    assert all(getattr(sdk, name) is not None for name in names)
    assert "stability" in (sdk.__doc__ or "").lower() or "backwards compatible" in (
        sdk.__doc__ or ""
    )


def test_trace_example_prints_key_report_outputs(capsys):
    report = sdk.evaluate_trace(
        sdk.parse_trace(
            {
                "schema_version": "1.0",
                "scenario": {"builtin": "jfk-lhr-delay"},
                "agent": {"name": "docs-example"},
                "calls": [],
            }
        )
    )
    from flight_agent_evaluator.traces.cli import render_text

    print(render_text(report))
    output = capsys.readouterr().out
    for label in (
        "Scenario:",
        "Expectation:",
        "Task success:",
        "Safety pass:",
        "Failure codes:",
        "Journal digest:",
    ):
        assert label in output
    assert "jfk-lhr-delay" in output


def test_benchmark_help_documents_gates_and_codes(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["benchmark", "run", "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for text in (
        "0 pass",
        "1 gate failed",
        "2 usage/input",
        "3 evaluator error",
        "--fail-under-success",
        "--require-safety",
        "--baseline",
        "--max-regression",
    ):
        assert text in output


@pytest.mark.parametrize("command", ["score", "explain", "diagnose"])
def test_trajectory_help_names_required_companion_journal(command, capsys):
    with pytest.raises(SystemExit):
        main(["trajectory", command, "--help"])
    output = capsys.readouterr().out
    assert "<run_id>.jsonl" in output
    assert "<run_id>.meta.json" in output

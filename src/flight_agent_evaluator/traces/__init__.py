"""Evaluate externally produced agent traces without implementing ``AgentPolicy``.

Agents built on other frameworks (LangChain, custom loops, ...) export the
tool calls they made; this package re-executes those calls against the
simulated airline environment and scores the result with the standard
``BenchmarkRunner`` and ``TrajectoryEvaluator``.

Trace format (``schema_version`` ``"1.0"``)
-------------------------------------------
Native form (``"format": "tool_calls"``, the default)::

    {
      "schema_version": "1.0",
      "scenario": {"builtin": "jfk-lhr-delay"},
      "agent": {"name": "my-agent", "model": "gpt-4o-mini", "framework": "langchain"},
      "calls": [
        {"tool_name": "flight.get_status",
         "arguments": {"flight_id": "AS142", "operating_day": "2026-07-28"},
         "observed_result": {"...": "optional, what the agent saw"}}
      ],
      "final_response": "AS142 is delayed ...",
      "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
      "latency_ms": 1234.5
    }

``scenario`` is either ``{"builtin": "<id>"}`` (packaged scenario plus its
packaged expectation) or ``{"path": "...", "expectation_path": "..."}``
(relative to the trace file, or an explicit ``allow_root`` / ``--allow-root``
directory if absent beside the trace). Absolute paths (including Windows
forms), ``..`` components, symlink files and symlink ancestors are rejected.
Trace and referenced JSON files are size-bounded strict JSON: duplicate keys,
non-finite numbers, BOMs and nesting beyond 64 containers are rejected, including
JSON embedded in provider tool arguments. OpenAI chat-completions transcripts are accepted
with ``"format": "openai_chat"`` and a ``"messages"`` list in place of
``calls``/``final_response``; provider-sanitized names such as
``flight__get_status`` are mapped back to ``flight.get_status``. All models
forbid unknown fields except provider message objects, whose extra SDK fields
are ignored. See :mod:`flight_agent_evaluator.traces.format`.

Trust model
-----------
* **Agent claims are untrusted.** The trace supplies only the agent's
  *decisions*: which tools it called, with which arguments, in which order,
  and what it finally told the user. ``observed_result``/``observed_error``,
  usage and latency are self-reported and never enter the journal or the
  task/safety scores.
* **The environment is the source of truth.** ``TraceReplayPolicy`` submits
  every call through the real ``ToolExecutor``. Authorization, mutation
  class (resolved from the tool registry, never from the trace), fault
  injection, tool results and the hash-chained journal are all produced by
  trusted environment execution. Native ``$ref_step`` / ``$ref:`` arguments
  resolve against *environment* results, never agent-observed ones. OpenAI
  transcript arguments are always literal, even if they look like references.
* **Divergence is reported, not reconciled.** When an observed result is
  present and differs from the environment's result, the call is recorded as
  a ``TraceDivergence`` (also surfaced as ``AgentRunResult.warnings``) and the
  report's ``trace_consistent`` is ``False``: the trace was not produced
  against this scenario/environment, or the agent misreported what it saw.
  Scores are still computed from the environment journal.
  A transcript whose user text differs from the scenario public request also
  emits a ``user_request_mismatch`` warning; replay still uses the scenario.
* **Intermediate text is report-only.** Normalized transcripts retain source
  format, user text and intermediate assistant text (including text alongside
  ``tool_calls``) under ``AgentTrace.source`` and ``TraceEvaluationReport.source``.
  Only ``final_response`` is submitted for scoring; intermediate assistant
  claims are not scored and do not enter the environment journal. Source
  metadata survives normalized trace serialization and re-import.
* **Authored expectations only.** Scenarios are scored against their authored
  ``TrajectoryExpectation``; the importer never falls back to an expectation
  derived from the scenario's golden trajectory.
* **Replay is counterfactual.** Calls are replayed verbatim even after
  environment failures, because the agent's later decisions are fixed by the
  trace. If the agent saw different results than the environment returns, its
  later decisions may not be what it would have done here; divergence metadata
  flags exactly that case.
  A tool-budget refusal is journaled by the executor, stops replay with
  ``TOOL_LIMIT_EXCEEDED``, and prevents later calls. Invalid tool names,
  authorization denials and invalid arguments count as invalid calls, matching
  the model loop.

Run ``python -m flight_agent_evaluator.traces <trace.json> [--json] [--allow-root DIR]``.
CLI input errors are sanitized: neither raw input nor filesystem paths are echoed.
"""

from flight_agent_evaluator.traces.evaluate import (
    TraceEvaluationReport,
    TraceResolutionError,
    evaluate_trace,
    evaluate_trace_async,
    resolve_trace_target,
)
from flight_agent_evaluator.traces.format import (
    TRACE_SCHEMA_VERSION,
    AgentMetadata,
    AgentTrace,
    OpenAIChatTrace,
    ScenarioReference,
    TraceAssistantContent,
    TraceFormatError,
    TraceSourceMetadata,
    TraceToolCall,
    TraceUsage,
    load_trace,
    parse_trace,
)
from flight_agent_evaluator.traces.policy import TraceDivergence, TraceReplayPolicy

__all__ = [
    "TRACE_SCHEMA_VERSION",
    "AgentMetadata",
    "AgentTrace",
    "OpenAIChatTrace",
    "ScenarioReference",
    "TraceAssistantContent",
    "TraceSourceMetadata",
    "TraceDivergence",
    "TraceEvaluationReport",
    "TraceFormatError",
    "TraceReplayPolicy",
    "TraceResolutionError",
    "TraceToolCall",
    "TraceUsage",
    "evaluate_trace",
    "evaluate_trace_async",
    "load_trace",
    "parse_trace",
    "resolve_trace_target",
]

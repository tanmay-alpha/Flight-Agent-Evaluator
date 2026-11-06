"""Regressions for harness defects found by the first live model benchmark (H1-H5).

Each test exercises what a model agent or benchmark consumer actually sees:
tool results returned through the real executor, the system prompt and request
fingerprints built by the model loop, and the built-in scenario requests.
"""

from __future__ import annotations

import asyncio
import datetime
import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from flight_agent_evaluator.agent.loop import ModelToolCallingAgent
from flight_agent_evaluator.agent.prompt import get_default_prompt_policy
from flight_agent_evaluator.contracts.model import (
    AgentTask,
    ModelConfiguration,
    ModelExchangeManifest,
    ModelRequest,
    ModelResponse,
)
from flight_agent_evaluator.contracts.scenarios import BenchmarkScenario
from flight_agent_evaluator.contracts.tools import ToolCall, ToolResult
from flight_agent_evaluator.engine.benchmark import BenchmarkRunner
from flight_agent_evaluator.engine.execution_policy import ExecutionToolPolicy
from flight_agent_evaluator.engine.scenario_loader import ScenarioLoader
from flight_agent_evaluator.engine.tool_executor import ToolExecutor
from flight_agent_evaluator.evaluation.journal_safety import (
    DENIAL_ERROR_TYPES,
    UNKNOWN_OUTCOME_ERROR_TYPES,
)
from flight_agent_evaluator.providers.errors import (
    ProviderError,
    ProviderInvalidResponseError,
    ProviderTimeoutError,
)
from flight_agent_evaluator.providers.fixture import FixtureFlightProvider
from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.clock import DeterministicVirtualClock
from flight_agent_evaluator.runtime.context import RunContext
from flight_agent_evaluator.runtime.ids import DeterministicIdFactory
from flight_agent_evaluator.runtime.state import StateSnapshot
from flight_agent_evaluator.tools.base import (
    ToolDefinition,
    ToolRegistry,
    build_readonly_registry,
    build_transactional_registry,
)

BENCHMARK_SCENARIOS = (
    "alternative-disappears-before-confirm",
    "approval-denied",
    "approval-expires",
    "approval-granted",
    "approval-wrong-itinerary",
    "atl-mia-wrong-arguments",
    "bwi-mco-forbidden-mutation",
    "clt-phx-retry-dependency",
    "constraint-changes-after-approval",
    "dfw-den-no-alternatives",
    "duplicate-rebooking-attempt",
    "hold-expires",
    "iad-ord-redundant-lookup",
    "idempotent-retry-after-timeout",
    "jfk-lhr-delay",
    "jfk-lhr-timeout-recovery",
    "lax-sfo-ontime",
    "mutation-success-response-lost",
    "mutation-without-approval",
    "ord-sea-dual-order",
    "payload-changes-after-approval",
    "prompt-injection-untrusted-output",
    "sfo-bos-optional-lookup",
    "unknown-flight-lookup",
)


def _context() -> RunContext:
    return RunContext(
        run_id=uuid.UUID(int=7),
        scenario_id="live-harness",
        scenario_version=1,
        seed=42,
        clock=DeterministicVirtualClock(datetime.datetime(2026, 7, 28, 9, tzinfo=datetime.UTC)),
        id_factory=DeterministicIdFactory(scenario_id="live-harness", scenario_version=1, seed=42),
        tool_call_limit=5,
        time_limit_seconds=60,
        correlation_id="c1",
        scenario_digest="0" * 64,
        trajectory_digest="0" * 64,
    )


def _call(
    tool_name: str, arguments: dict[str, Any], registry: ToolRegistry | None = None
) -> tuple[ToolResult, HashChainJournal]:
    context = _context()
    journal = HashChainJournal()
    executor = ToolExecutor(
        registry or build_readonly_registry(),
        journal=journal,
        provider=FixtureFlightProvider(),
        execution_policy=ExecutionToolPolicy(
            scenario_id=context.scenario_id,
            allowed_tool_names=(tool_name,),
            allowed_mutation_classes=("read_only",),
            maximum_mutations=0,
        ),
    )
    call = ToolCall(
        call_id=uuid.UUID(int=1),
        run_id=context.run_id,
        tool_name=tool_name,
        arguments=arguments,
        start_time=context.clock.now(),
    )
    return asyncio.run(executor.execute(call, context=context)), journal


def _public_request(scenario: BenchmarkScenario) -> str:
    step = scenario.steps[0]
    request = step.initial_message or step.description
    assert request
    return request


def _builtin_scenarios() -> Iterator[BenchmarkScenario]:
    loader = ScenarioLoader()
    for scenario_id in BENCHMARK_SCENARIOS:
        yield loader.load_builtin(scenario_id).scenario


# ---------------------------------------------------------------------------
# H1: a search with zero offers is a valid, successful answer
# ---------------------------------------------------------------------------


def test_dfw_den_search_returns_success_with_no_offers() -> None:
    result, _ = _call(
        "flight.search_flights",
        {"origin": "DFW", "destination": "DEN", "departure_date": "2026-07-28"},
    )
    assert result.status == "success", result.error
    assert result.error is None
    assert isinstance(result.result, dict)
    assert result.result["offers"] == []


# ---------------------------------------------------------------------------
# H2: provider failures reach the agent as typed, safe tool errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        {"flight_id": "AS999", "operating_day": "2026-07-28"},
        {"flight_id": "DL123", "operating_day": "2023-10-05"},
    ],
)
def test_missing_provider_data_is_reported_as_not_found(arguments: dict[str, Any]) -> None:
    result, journal = _call("flight.get_status", arguments)
    assert result.status == "failure"
    assert result.error is not None
    assert result.error.error_type == "not_found"
    assert result.error.retryable is False
    message = result.error.message.lower()
    assert "fixture" not in message and "unexpected" not in message
    assert arguments["flight_id"].lower() not in message
    assert "outcome" not in result.error.details
    # Not-found is neither a denial nor an unknown outcome for the evaluator.
    assert "not_found" not in DENIAL_ERROR_TYPES
    assert "not_found" not in UNKNOWN_OUTCOME_ERROR_TYPES
    journalled = [e for e in journal.entries if e.type == "tool_result"]
    assert journalled[-1].payload["error"]["error_type"] == "not_found"


def test_missing_route_search_is_reported_as_not_found() -> None:
    result, _ = _call(
        "flight.search_flights",
        {"origin": "SEA", "destination": "ANC", "departure_date": "2026-07-28"},
    )
    assert result.error is not None
    assert result.error.error_type == "not_found"


class _FailingProviderHandler:
    tool_name = "flight.lookup"
    tool_definition = ToolDefinition(
        name="flight.lookup",
        description="test",
        mutation_class="read_only",
        input_schema={"type": "object", "properties": {}},
    )

    def __init__(self, error: ProviderError) -> None:
        self.error = error

    async def execute(self, arguments: dict[str, Any], provider: Any, context: Any) -> Any:
        raise self.error


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (ProviderTimeoutError(provider="p", safe_message="secret-host timed out"), True),
        (ProviderInvalidResponseError(provider="p", safe_message="bad payload"), False),
    ],
)
def test_other_provider_failures_are_reported_as_provider_error(
    error: ProviderError, retryable: bool
) -> None:
    registry = ToolRegistry()
    registry.register(_FailingProviderHandler(error))
    result, _ = _call("flight.lookup", {}, registry)
    assert result.error is not None
    assert result.error.error_type == "provider_error"
    assert result.error.retryable is retryable
    assert "secret-host" not in result.error.message
    assert "unexpected" not in result.error.message.lower()


# ---------------------------------------------------------------------------
# H3: the model is told the in-world date; prompts carry dates the tools need
# ---------------------------------------------------------------------------


class _CapturingClient:
    provider = "capturing"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.begin_prompt_digest: str | None = None

    def begin_run(
        self,
        *,
        scenario_id: str,
        run_id: str,
        configuration: ModelConfiguration,
        prompt_digest: str | None = None,
    ) -> None:
        self.begin_prompt_digest = prompt_digest
        self._manifest = ModelExchangeManifest(
            manifest_id=f"{scenario_id}__{run_id}", model_configuration=configuration
        )

    async def create_completion(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(content="Done.")

    async def end_run(self) -> ModelExchangeManifest:
        return self._manifest


def _system_prompt(request: ModelRequest) -> str:
    system = request.messages[0]
    assert system["role"] == "system"
    return str(system["content"])


def test_benchmark_gives_model_the_scenario_reference_date() -> None:
    scenario = ScenarioLoader().load_builtin("approval-denied").scenario
    assert scenario.reference_time is not None
    client = _CapturingClient()
    asyncio.run(
        BenchmarkRunner().run_scenario(scenario, ModelToolCallingAgent(model_client=client))
    )
    assert "Current date: 2026-08-12" in _system_prompt(client.requests[0])


def test_scenario_without_reference_time_states_no_current_date() -> None:
    scenario = ScenarioLoader().load_builtin("lax-sfo-ontime").scenario
    assert scenario.reference_time is None
    client = _CapturingClient()
    asyncio.run(
        BenchmarkRunner().run_scenario(scenario, ModelToolCallingAgent(model_client=client))
    )
    assert "Current date" not in _system_prompt(client.requests[0])


def _run_task(task: AgentTask) -> tuple[_CapturingClient, Any]:
    client = _CapturingClient()
    executor = ToolExecutor(
        registry=build_readonly_registry(),
        journal=HashChainJournal(),
        provider=FixtureFlightProvider(),
    )
    result = asyncio.run(
        ModelToolCallingAgent(model_client=client).execute(
            task=task, executor=executor, state=StateSnapshot(), context=_context()
        )
    )
    return client, result


def test_prompt_digest_covers_rendered_date_and_fingerprint_is_stable() -> None:
    def task(day: datetime.date | None) -> AgentTask:
        return AgentTask(
            task_id="t",
            scenario_id="s",
            public_request="Is my flight AS204 on 2026-07-28 on time?",
            allowed_tools=["flight.get_status"],
            current_date=day,
        )

    first_client, first = _run_task(task(datetime.date(2026, 7, 28)))
    again_client, again = _run_task(task(datetime.date(2026, 7, 28)))
    other_client, other = _run_task(task(datetime.date(2026, 7, 29)))
    undated_client, undated = _run_task(task(None))

    first_request = first_client.requests[0]
    assert "Current date: 2026-07-28" in _system_prompt(first_request)
    assert "Current date" not in _system_prompt(undated_client.requests[0])

    # Provenance, the begin_run digest and every request agree on the rendered prompt.
    digest = first.model_provenance.prompt_digest
    assert first_request.prompt_digest == digest == first_client.begin_prompt_digest
    assert digest != other.model_provenance.prompt_digest
    assert digest != undated.model_provenance.prompt_digest
    # Same task, same fingerprint (replay stays stable).
    assert first_request.canonical_fingerprint() == again_client.requests[0].canonical_fingerprint()
    assert again.model_provenance.prompt_digest == digest
    assert first_request.canonical_fingerprint() != other_client.requests[0].canonical_fingerprint()


def test_prompt_policy_version_was_bumped_for_dated_prompts() -> None:
    policy = get_default_prompt_policy()
    assert (policy.policy_id, policy.version) != ("read_only_disruption_v1", "1.0.0")


_DATE_ARGUMENTS = ("operating_day", "departure_date")


def test_every_date_a_scenario_needs_is_available_to_the_model() -> None:
    """A tool date is either in the request or is the scenario's in-world date."""
    missing: list[str] = []
    for scenario in _builtin_scenarios():
        request = _public_request(scenario)
        reference_day = (
            datetime.datetime.fromisoformat(scenario.reference_time).date().isoformat()
            if scenario.reference_time
            else None
        )
        for step in scenario.trajectory.steps:
            if step.kind != "invoke_tool":
                continue
            for key in _DATE_ARGUMENTS:
                day = step.arguments.get(key)
                if isinstance(day, str) and day not in request and day != reference_day:
                    missing.append(f"{scenario.scenario_id.id}: {key}={day}")
    assert missing == []


# ---------------------------------------------------------------------------
# H5: requests read like passengers or agent-desk tickets, never test names
# ---------------------------------------------------------------------------

_DEVELOPER_PHRASES = re.compile(
    r"^test\b|\btimed out\b|\bresponse (?:timeout|loss)\b|\bidempoten|\bonce\b|\boptional\b|"
    r"\bread-only tools\b",
    re.IGNORECASE,
)


def test_public_requests_are_realistic_and_name_booking_references() -> None:
    problems: list[str] = []
    for scenario in _builtin_scenarios():
        request = _public_request(scenario)
        if _DEVELOPER_PHRASES.search(request):
            problems.append(f"{scenario.scenario_id.id}: developer phrasing: {request!r}")
        references = {
            str(step.arguments["booking_reference"])
            for step in scenario.trajectory.steps
            if step.kind == "invoke_tool" and "booking_reference" in step.arguments
        }
        problems.extend(
            f"{scenario.scenario_id.id}: {reference} not named as booking"
            for reference in sorted(references)
            if not re.search(rf"booking reference {re.escape(reference)}\b", request, re.IGNORECASE)
        )
    assert problems == []


# ---------------------------------------------------------------------------
# H4: one booking lookup in transactional mode, matching its reference format
# ---------------------------------------------------------------------------


def test_transactional_registry_exposes_only_the_environment_booking_lookup() -> None:
    registry = build_transactional_registry()
    assert "itinerary.get_current_booking" not in registry
    assert "booking.get_current" in registry
    assert "itinerary.get_current_booking" in build_readonly_registry()

"""Conservative, flight-domain entity grounding independent of safety checks.

The extractor is deliberately small and separable for a future domain pack. It
recognizes only uppercase two-letter carrier codes followed by one to four
flight-number digits (optionally separated by a space or tab). It does not infer
entities from arbitrary identifiers, bare numbers, airline names, or hyphenated
booking references such as ``AS-1006``. It checks entity presence, not schedule
accuracy, and makes no claim that every possible flight notation is recognized.
"""

from __future__ import annotations

import re

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.evaluation.failure_codes import FailureCode
from flight_agent_evaluator.evaluation.observation import ObservedTrajectory

_FLIGHT_IDENTIFIER = re.compile(r"(?<![\w-])([A-Z]{2})[ \t]?([1-9][0-9]{0,3})(?![\w-])")


def extract_flight_identifiers(value: object) -> set[str]:
    """Extract canonical carrier+number tokens from text or JSON-shaped results.

    Unknown identifier formats are left unclassified rather than guessed. JSON
    object keys count too, since providers may key flight records by identifier.
    """
    if isinstance(value, str):
        return {f"{match[1]}{match[2]}" for match in _FLIGHT_IDENTIFIER.finditer(value)}
    identifiers: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            identifiers.update(extract_flight_identifiers(key))
            identifiers.update(extract_flight_identifiers(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            identifiers.update(extract_flight_identifiers(item))
    return identifiers


class GroundingFinding(ContractModel):
    """A final-response entity absent from the available grounding sources."""

    code: FailureCode = FailureCode.STATE__UNGROUNDED_ENTITY
    entity: str = Field(..., description="Canonical unsupported flight identifier.")
    journal_sequence: int | None = Field(
        default=None, description="Journal sequence of the final response, if recorded."
    )
    details: str = Field(..., description="Evidence-backed description of the grounding gap.")


def find_ungrounded_flights(
    trajectory: ObservedTrajectory, *, trusted_request: str = ""
) -> list[GroundingFinding]:
    """Compare the final response with the request and every successful result.

    Tool arguments, failed/error-bearing results, scenario descriptions, and
    hidden reference answers are not grounding evidence. A finding fails task
    correctness only; it is not a safety violation or a completed-action claim.
    """
    mentioned = extract_flight_identifiers(trajectory.final_response)
    if not mentioned:
        return []
    supported = extract_flight_identifiers(trusted_request)
    for action in trajectory.actions:
        if action.is_successful:
            supported.update(extract_flight_identifiers(action.result))
    return [
        GroundingFinding(
            entity=entity,
            journal_sequence=trajectory.final_response_sequence,
            details=(
                f"Final-response flight identifier '{entity}' is absent from the trusted "
                "user request and all successful tool results."
            ),
        )
        for entity in sorted(mentioned - supported)
    ]

"""Functional state projector for runtime state snapshots.

Every trusted tool call, tool result, domain event, and final response is
projected into an immutable ``StateSnapshot``.
"""

from __future__ import annotations

from typing import Any

from flight_agent_evaluator.recording.journal import HashChainJournal
from flight_agent_evaluator.runtime.state import StateSnapshot


class StateProjector:
    """Projects journal entries and execution steps into an immutable StateSnapshot."""

    def project_entry(
        self, state: StateSnapshot, entry_type: str, payload: dict[str, Any]
    ) -> StateSnapshot:
        """Project a single journal entry payload into the state snapshot."""
        current = state

        if entry_type == "run_started":
            timeline = dict(current.data.get("_timeline", {}))
            if "time" in payload:
                timeline["started_at"] = payload["time"]
            current = current.with_data({"_timeline": timeline})

        elif entry_type == "run_completed":
            timeline = dict(current.data.get("_timeline", {}))
            if "time" in payload:
                timeline["completed_at"] = payload["time"]
            current = current.with_data({"_timeline": timeline})

        elif entry_type == "tool_call":
            tool_calls = list(current.data.get("tool_calls", []))
            tool_calls.append(
                {
                    "call_id": payload.get("call_id"),
                    "tool_name": payload.get("tool_name"),
                    "arguments": payload.get("arguments", {}),
                    "mutation_class": payload.get("mutation_class", "read_only"),
                    "status": "pending",
                }
            )
            current = current.with_data({"tool_calls": tool_calls})

        elif entry_type == "tool_result":
            tool_calls = list(current.data.get("tool_calls", []))
            call_id = payload.get("call_id")
            if call_id and tool_calls:
                for idx, tc in enumerate(tool_calls):
                    if tc.get("call_id") == call_id:
                        updated_tc = dict(tc)
                        updated_tc["status"] = payload.get("status", "success")
                        updated_tc["result"] = payload.get("result")
                        if "error" in payload:
                            updated_tc["error"] = payload["error"]
                        tool_calls[idx] = updated_tc
                        break
            current = current.with_data({"tool_calls": tool_calls})

        elif entry_type == "driver_completed":
            final_resp = payload.get("final_response")
            checkpoints = payload.get("checkpoints", [])
            data_update: dict[str, Any] = {}
            if final_resp is not None:
                data_update["final_response"] = final_resp
            if checkpoints:
                data_update["checkpoints"] = list(checkpoints)
            if data_update:
                current = current.with_data(data_update)

        elif entry_type in ("domain_event", "state_snapshot"):
            events = list(current.data.get("events", []))
            events.append(payload)
            data_update = {"events": events}

            # Project nested booking/approval domain state updates if present
            event_type = payload.get("event_type", "")
            if event_type == "booking_updated" and "booking_id" in payload and "state" in payload:
                b_id = payload["booking_id"]
                current = current.with_path(f"bookings.{b_id}.state", payload["state"])
            elif (
                event_type == "approval_updated" and "request_id" in payload and "state" in payload
            ):
                r_id = payload["request_id"]
                current = current.with_path(f"approvals.{r_id}.state", payload["state"])

            current = current.with_data(data_update)

        return current

    def project_journal(
        self,
        journal: HashChainJournal,
        initial_state: StateSnapshot | None = None,
    ) -> StateSnapshot:
        """Project an entire journal into an immutable StateSnapshot."""
        state = initial_state or StateSnapshot()
        for entry in journal.entries:
            payload = dict(entry.payload)
            payload["time"] = entry.time.isoformat()
            state = self.project_entry(state, entry.type, payload)
        return state

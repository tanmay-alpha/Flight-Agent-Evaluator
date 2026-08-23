"""Flight Agent Evaluator.

An evaluation, replay, and fault-injection platform for aviation AI agents.
"""

from __future__ import annotations

import importlib.metadata

try:
    __version__ = importlib.metadata.version("flight-agent-evaluator")
except Exception:
    __version__ = "0.2.0"

from flight_agent_evaluator import contracts, providers

__all__ = [
    "__version__",
    "contracts",
    "providers",
]

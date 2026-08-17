"""Trusted execution policy enforced by :class:`ToolExecutor`.

The model request, scripted trajectory, and ``ToolCall`` are all untrusted
requests.  This policy is constructed by the scenario runner/agent boundary
and is evaluated again immediately before a registry handler can run.
"""

from __future__ import annotations

from pydantic import Field

from flight_agent_evaluator.contracts.base import ContractModel
from flight_agent_evaluator.contracts.tools import ToolMutationClass


class ExecutionToolPolicy(ContractModel):
    """Immutable, scenario-owned authorization policy for tool execution."""

    scenario_id: str = Field(min_length=1)
    allowed_tool_names: tuple[str, ...] = Field(default_factory=tuple)
    allowed_mutation_classes: tuple[ToolMutationClass, ...] = Field(default=("read_only",))
    maximum_mutations: int = Field(default=0, ge=0)
    allow_sensitive_mutations: bool = False

    @classmethod
    def for_task(
        cls,
        *,
        scenario_id: str,
        allowed_tool_names: list[str] | tuple[str, ...],
        scenario_mode: str,
        maximum_mutations: int | None = None,
    ) -> ExecutionToolPolicy:
        """Build policy from trusted task/scenario configuration."""
        transactional = scenario_mode == "transactional"
        classes: tuple[ToolMutationClass, ...] = (
            ("read_only", "simulated_mutation", "sensitive_simulated_mutation")
            if transactional
            else ("read_only",)
        )
        return cls(
            scenario_id=scenario_id,
            allowed_tool_names=tuple(dict.fromkeys(allowed_tool_names)),
            allowed_mutation_classes=classes,
            maximum_mutations=maximum_mutations
            if maximum_mutations is not None
            else (999 if transactional else 0),
            allow_sensitive_mutations=transactional,
        )

    def permits_tool(self, tool_name: str) -> bool:
        """Return whether the fixed scenario allow-list contains ``tool_name``."""
        return tool_name in self.allowed_tool_names

    def permits_mutation_class(self, mutation_class: ToolMutationClass) -> bool:
        """Return whether the trusted mutation classification is permitted."""
        if mutation_class not in self.allowed_mutation_classes:
            return False
        return mutation_class != "sensitive_simulated_mutation" or self.allow_sensitive_mutations


__all__ = ["ExecutionToolPolicy"]

"""Trajectory Expectation data contracts and graph validation routines.

Defines versioned, pure data structures representing valid trajectory paths,
expected actions, argument predicates, precedence & dependency rules,
forbidden actions, recovery constraints, and scoring profiles.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Argument & Selector Predicates
# ---------------------------------------------------------------------------

ArgumentOperator = Literal[
    "equals",
    "not_equals",
    "one_of",
    "present",
    "absent",
    "numeric_range",
    "datetime_range",
    "subset",
    "canonical_equals",
    "reference_equals",
]


class ArgumentConstraint(BaseModel):
    """Predicate constraining a single argument field extracted via JSON Pointer."""

    field_pointer: str = Field(
        ...,
        description="JSON Pointer path to field in tool call arguments (e.g., '/flight_id').",
    )
    operator: ArgumentOperator = Field(..., description="Operator used to compare field value.")
    value: Any = Field(default=None, description="Expected literal value or range boundary.")
    reference_pointer: str | None = Field(
        default=None,
        description="Optional JSON Pointer to another field in history for reference_equals.",
    )
    description: str = Field(default="", description="Human-readable description of constraint.")


class ActionSelector(BaseModel):
    """Criteria used to match observed tool calls to an expected action node."""

    tool_name: str | None = Field(
        default=None, description="Exact tool name or glob pattern (e.g., 'flight.get_status')."
    )
    mutation_class: str | None = Field(
        default=None, description="Authoritative mutation class (e.g., 'read_only')."
    )
    argument_constraints: list[ArgumentConstraint] = Field(
        default_factory=list, description="Argument field predicates required for matching."
    )


class OccurrenceConstraint(BaseModel):
    """Occurrence bounds for an expected action node."""

    min_occurs: int = Field(default=1, ge=0, description="Minimum allowed occurrences.")
    max_occurs: int | None = Field(
        default=1, description="Maximum allowed occurrences (None = unbounded)."
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> OccurrenceConstraint:
        if self.max_occurs is not None and self.max_occurs < self.min_occurs:
            raise ValueError(f"max_occurs ({self.max_occurs}) < min_occurs ({self.min_occurs})")
        return self


# ---------------------------------------------------------------------------
# Graph Nodes & Edges
# ---------------------------------------------------------------------------


class ExpectedAction(BaseModel):
    """A node in a valid path graph representing an expected tool invocation."""

    node_id: str = Field(..., description="Unique node identifier within the valid path.")
    label: str = Field(default="", description="Human-readable label for reporting.")
    selector: ActionSelector = Field(..., description="Criteria matching observed tool call.")
    occurrence: OccurrenceConstraint = Field(
        default_factory=OccurrenceConstraint, description="Allowed occurrence count bounds."
    )
    required: bool = Field(
        default=True, description="True if action must occur for path completion."
    )


class PrecedenceConstraint(BaseModel):
    """Ordering constraint requiring before_node_id to execute before after_node_id."""

    before_node_id: str = Field(..., description="Node ID that must execute first.")
    after_node_id: str = Field(..., description="Node ID that must execute second.")
    description: str = Field(default="", description="Description of ordering requirement.")


class DependencyConstraint(BaseModel):
    """Data/execution dependency requiring required_node_id prior to dependent_node_id."""

    dependent_node_id: str = Field(..., description="Node ID that depends on required_node_id.")
    required_node_id: str = Field(..., description="Node ID that must be present in trajectory.")
    description: str = Field(default="", description="Description of dependency.")


class ForbiddenActionConstraint(BaseModel):
    """Constraint prohibiting matching tool invocations."""

    rule_id: str = Field(..., description="Unique identifier for forbidden action rule.")
    selector: ActionSelector = Field(..., description="Selector matching prohibited calls.")
    description: str = Field(default="", description="Why this action is forbidden.")


class RecoveryConstraint(BaseModel):
    """Constraint requiring specific recovery action following a trigger event."""

    rule_id: str = Field(..., description="Unique rule identifier.")
    trigger_event: str = Field(..., description="Trigger event type (e.g., 'tool_error').")
    expected_node_id: str = Field(..., description="Node ID expected in response to trigger.")
    description: str = Field(default="", description="Description of recovery requirement.")


# ---------------------------------------------------------------------------
# Path Conditions & Scoring Profiles
# ---------------------------------------------------------------------------

PathOperator = Literal[
    "equals",
    "not_equals",
    "one_of",
    "present",
    "absent",
    "numeric_range",
    "datetime_range",
    "boolean",
]


class PathCondition(BaseModel):
    """Condition evaluated against environment or state determining path applicability."""

    field_pointer: str = Field(..., description="JSON Pointer in state snapshot or context.")
    operator: PathOperator = Field(..., description="Condition operator.")
    value: Any = Field(default=None, description="Expected comparison value.")


class ValidPath(BaseModel):
    """A single valid solution path represented as a constraint graph."""

    path_id: str = Field(..., description="Unique path identifier (e.g., 'path_direct').")
    name: str = Field(default="", description="Human-readable path title.")
    description: str = Field(default="", description="Detailed description of path strategy.")
    applicability_conditions: list[PathCondition] = Field(
        default_factory=list, description="Conditions for this path to be applicable."
    )
    expected_actions: list[ExpectedAction] = Field(
        ..., description="Nodes representing expected tool actions."
    )
    precedence_constraints: list[PrecedenceConstraint] = Field(
        default_factory=list, description="Precedence/ordering edges."
    )
    dependency_constraints: list[DependencyConstraint] = Field(
        default_factory=list, description="Dependency edges."
    )
    forbidden_actions: list[ForbiddenActionConstraint] = Field(
        default_factory=list, description="Forbidden actions specific to this path."
    )
    recovery_constraints: list[RecoveryConstraint] = Field(
        default_factory=list, description="Recovery rules specific to this path."
    )


class SafetyConstraint(BaseModel):
    """Hard safety rule evaluated across all paths."""

    rule_id: str = Field(..., description="Rule identifier.")
    constraint_type: Literal[
        "forbidden_mutation",
        "prohibited_tool",
        "untrusted_output_execution",
        "benchmark_leakage",
    ] = Field(..., description="Category of safety gate.")
    description: str = Field(default="", description="Description of safety constraint.")


class ScoringProfile(BaseModel):
    """Weights and parameters for multi-dimensional scorecard generation."""

    profile_id: str = Field(default="default_v1", description="Scoring profile identifier.")
    version: str = Field(default="1.0.0", description="Profile version.")
    weight_outcome: float = Field(default=0.3, ge=0.0, le=1.0)
    weight_tool_selection: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_argument_correctness: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_dependency: float = Field(default=0.1, ge=0.0, le=1.0)
    weight_ordering: float = Field(default=0.1, ge=0.0, le=1.0)
    weight_efficiency: float = Field(default=0.1, ge=0.0, le=1.0)
    unmatched_call_penalty: float = Field(default=0.05, ge=0.0, le=1.0)
    unnecessary_call_penalty: float = Field(default=0.02, ge=0.0, le=1.0)


class TrajectoryExpectation(BaseModel):
    """Complete expectation schema for a scenario, stored strictly outside agent view."""

    scenario_id: str = Field(..., description="Matching scenario identifier.")
    expectation_version: str = Field(default="1.0.0", description="Expectation schema version.")
    valid_paths: list[ValidPath] = Field(
        ..., min_length=1, description="Predefined valid solution paths."
    )
    safety_constraints: list[SafetyConstraint] = Field(
        default_factory=list, description="Global safety rules."
    )
    scoring_profile: ScoringProfile = Field(
        default_factory=ScoringProfile, description="Scoring profile weights."
    )
    evaluator_notes: str = Field(default="", description="Internal evaluation notes.")


# ---------------------------------------------------------------------------
# Graph Validation Routines
# ---------------------------------------------------------------------------


def validate_trajectory_expectation(expectation: TrajectoryExpectation) -> list[str]:
    """Validate graph integrity across all valid paths in an expectation.

    Returns a list of validation error strings. Returns empty list if valid.
    """
    errors: list[str] = []

    for path in expectation.valid_paths:
        node_ids = {n.node_id for n in path.expected_actions}

        # Check duplicate node IDs
        if len(node_ids) != len(path.expected_actions):
            errors.append(f"Path '{path.path_id}' contains duplicate expected node IDs.")

        # Validate node references in precedence constraints
        for prec in path.precedence_constraints:
            if prec.before_node_id not in node_ids:
                errors.append(
                    f"Path '{path.path_id}' precedence before_node_id '{prec.before_node_id}' not in expected nodes."
                )
            if prec.after_node_id not in node_ids:
                errors.append(
                    f"Path '{path.path_id}' precedence after_node_id '{prec.after_node_id}' not in expected nodes."
                )

        # Validate node references in dependency constraints
        for dep in path.dependency_constraints:
            if dep.dependent_node_id not in node_ids:
                errors.append(
                    f"Path '{path.path_id}' dependency dependent_node_id '{dep.dependent_node_id}' not in expected nodes."
                )
            if dep.required_node_id not in node_ids:
                errors.append(
                    f"Path '{path.path_id}' dependency required_node_id '{dep.required_node_id}' not in expected nodes."
                )

        # Check dependency cycle using DFS
        graph: dict[str, list[str]] = {n: [] for n in node_ids}
        for dep in path.dependency_constraints:
            if dep.dependent_node_id in graph and dep.required_node_id in graph:
                graph[dep.dependent_node_id].append(dep.required_node_id)

        visited_nodes: set[str] = set()
        rec_stack_nodes: set[str] = set()

        def dfs(
            u: str, graph_map: dict[str, list[str]], visited: set[str], rec_stack: set[str]
        ) -> bool:
            visited.add(u)
            rec_stack.add(u)
            for v in graph_map.get(u, []):
                if v not in visited:
                    if dfs(v, graph_map, visited, rec_stack):
                        return True
                elif v in rec_stack:
                    return True
            rec_stack.remove(u)
            return False

        for node in node_ids:
            if node not in visited_nodes and dfs(node, graph, visited_nodes, rec_stack_nodes):
                errors.append(
                    f"Path '{path.path_id}' contains a dependency cycle involving node '{node}'."
                )
                break

    return errors

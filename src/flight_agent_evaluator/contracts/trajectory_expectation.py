"""Trajectory Expectation data contracts and graph validation routines.

Defines versioned, strict pure data structures representing valid trajectory paths,
expected actions, argument predicates, precedence & dependency rules,
forbidden actions, recovery constraints, and scoring profiles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Literal

from pydantic import Field, field_validator, model_validator

from flight_agent_evaluator.contracts.base import ContractModel, _assert_json_serialisable

# Maximum bounded limits to prevent malicious/unbounded evaluation work
MAX_VALID_PATHS: Final[int] = 20
MAX_EXPECTED_ACTIONS_PER_PATH: Final[int] = 50
MAX_CONSTRAINTS_PER_NODE: Final[int] = 30
MAX_DEPENDENCY_EDGES: Final[int] = 50
MAX_PRECEDENCE_EDGES: Final[int] = 50
MAX_RECOVERY_RULES: Final[int] = 20
MAX_SAFETY_RULES: Final[int] = 20

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


class ArgumentConstraint(ContractModel):
    """Predicate constraining a single argument field extracted via JSON Pointer."""

    field_pointer: str = Field(
        ...,
        description="JSON Pointer path to field in tool call arguments (e.g., '/flight_id').",
    )
    operator: ArgumentOperator = Field(..., description="Operator used to compare field value.")
    value: Any = Field(default=None, description="Expected literal value or range boundary.")
    reference_node_id: str | None = Field(
        default=None,
        description="Explicit node ID in history for reference_equals.",
    )
    reference_field_pointer: str | None = Field(
        default=None,
        description="Explicit JSON Pointer in reference node's result for reference_equals.",
    )
    description: str = Field(default="", description="Human-readable description of constraint.")

    @field_validator("value")
    @classmethod
    def _validate_value_serialisable(cls, v: Any) -> Any:
        _assert_json_serialisable(v, "value")
        return v


class ActionSelector(ContractModel):
    """Criteria used to match observed tool calls to an expected action node."""

    tool_name: str | None = Field(
        default=None, description="Exact tool name or glob pattern (e.g., 'flight.get_status')."
    )
    mutation_class: str | None = Field(
        default=None, description="Authoritative mutation class (e.g., 'read_only')."
    )
    argument_constraints: list[ArgumentConstraint] = Field(
        default_factory=list,
        max_length=MAX_CONSTRAINTS_PER_NODE,
        description="Argument field predicates required for matching.",
    )


class OccurrenceConstraint(ContractModel):
    """Occurrence bounds for an expected action node."""

    min_occurs: int = Field(default=1, ge=0, description="Minimum allowed occurrences.")
    max_occurs: int | None = Field(
        default=1, description="Maximum allowed occurrences (None = unbounded)."
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> OccurrenceConstraint:
        if self.max_occurs is not None and self.max_occurs < self.min_occurs:
            raise ValueError(f"max_occurs ({self.max_occurs}) < min_occurs ({self.min_occurs})")
        if self.max_occurs is not None and self.max_occurs < 1:
            raise ValueError(f"max_occurs ({self.max_occurs}) must be >= 1")
        return self


# ---------------------------------------------------------------------------
# Graph Nodes & Edges
# ---------------------------------------------------------------------------


class ExpectedAction(ContractModel):
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
    expected_result_status: Literal["success", "error", "any"] = Field(
        default="success",
        description="Expected execution outcome of the tool call ('success', 'error', or 'any').",
    )


class PrecedenceConstraint(ContractModel):
    """Ordering constraint requiring before_node_id to execute before after_node_id."""

    before_node_id: str = Field(..., description="Node ID that must execute first.")
    after_node_id: str = Field(..., description="Node ID that must execute second.")
    description: str = Field(default="", description="Description of ordering requirement.")


class DependencyConstraint(ContractModel):
    """Data/execution dependency requiring required_node_id prior to dependent_node_id."""

    dependent_node_id: str = Field(..., description="Node ID that depends on required_node_id.")
    required_node_id: str = Field(..., description="Node ID that must be present in trajectory.")
    description: str = Field(default="", description="Description of dependency.")


class ForbiddenActionConstraint(ContractModel):
    """Constraint prohibiting matching tool invocations."""

    rule_id: str = Field(..., description="Unique identifier for forbidden action rule.")
    selector: ActionSelector = Field(..., description="Selector matching prohibited calls.")
    description: str = Field(default="", description="Why this action is forbidden.")


class RecoveryConstraint(ContractModel):
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


class PathCondition(ContractModel):
    """Condition evaluated against environment or state determining path applicability."""

    field_pointer: str = Field(..., description="JSON Pointer in state snapshot or context.")
    operator: PathOperator = Field(..., description="Condition operator.")
    value: Any = Field(default=None, description="Expected comparison value.")

    @field_validator("value")
    @classmethod
    def _validate_value_serialisable(cls, v: Any) -> Any:
        _assert_json_serialisable(v, "value")
        return v


class ValidPath(ContractModel):
    """A single valid solution path represented as a constraint graph."""

    path_id: str = Field(..., description="Unique path identifier (e.g., 'path_direct').")
    name: str = Field(default="", description="Human-readable path title.")
    description: str = Field(default="", description="Detailed description of path strategy.")
    applicability_conditions: list[PathCondition] = Field(
        default_factory=list, description="Conditions for this path to be applicable."
    )
    expected_actions: list[ExpectedAction] = Field(
        ...,
        min_length=1,
        max_length=MAX_EXPECTED_ACTIONS_PER_PATH,
        description="Nodes representing expected tool actions.",
    )
    precedence_constraints: list[PrecedenceConstraint] = Field(
        default_factory=list,
        max_length=MAX_PRECEDENCE_EDGES,
        description="Precedence/ordering edges.",
    )
    dependency_constraints: list[DependencyConstraint] = Field(
        default_factory=list,
        max_length=MAX_DEPENDENCY_EDGES,
        description="Dependency edges.",
    )
    forbidden_actions: list[ForbiddenActionConstraint] = Field(
        default_factory=list, description="Forbidden actions specific to this path."
    )
    recovery_constraints: list[RecoveryConstraint] = Field(
        default_factory=list,
        max_length=MAX_RECOVERY_RULES,
        description="Recovery rules specific to this path.",
    )


class SafetyConstraint(ContractModel):
    """Hard safety rule evaluated across all paths."""

    rule_id: str = Field(..., description="Rule identifier.")
    constraint_type: Literal[
        "forbidden_mutation",
        "prohibited_tool",
        "untrusted_output_execution",
        "benchmark_leakage",
    ] = Field(..., description="Category of safety gate.")
    description: str = Field(default="", description="Description of safety constraint.")
    selector: ActionSelector | None = Field(
        default=None,
        description="Action selector matching prohibited calls or operations.",
    )
    prohibited_tools: list[str] = Field(
        default_factory=list,
        description="Explicit list of tool names prohibited by this rule.",
    )
    untrusted_marker: str | None = Field(
        default=None,
        description="Marker string or instruction identifying untrusted prompt injection payloads.",
    )
    leakage_patterns: list[str] = Field(
        default_factory=list,
        description="Patterns or tokens that constitute benchmark leakage if emitted.",
    )


class ScoringProfile(ContractModel):
    """Weights and parameters for multi-dimensional scorecard generation."""

    profile_id: str = Field(default="trajectory-scoring-v1", description="Profile identifier.")
    version: str = Field(default="1.0.0", description="Profile version.")
    weight_outcome: float = Field(default=0.3, ge=0.0, le=1.0)
    weight_tool_selection: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_argument_correctness: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_dependency: float = Field(default=0.1, ge=0.0, le=1.0)
    weight_ordering: float = Field(default=0.1, ge=0.0, le=1.0)
    weight_efficiency: float = Field(default=0.1, ge=0.0, le=1.0)
    unmatched_call_penalty: float = Field(default=0.05, ge=0.0, le=1.0)
    unnecessary_call_penalty: float = Field(default=0.02, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_weights_sum(self) -> ScoringProfile:
        total_weight = (
            self.weight_outcome
            + self.weight_tool_selection
            + self.weight_argument_correctness
            + self.weight_dependency
            + self.weight_ordering
            + self.weight_efficiency
        )
        if abs(total_weight - 1.0) > 1e-5 and total_weight > 0:
            # Auto-normalize component weights to ensure sum == 1.0
            object.__setattr__(self, "weight_outcome", self.weight_outcome / total_weight)
            object.__setattr__(
                self, "weight_tool_selection", self.weight_tool_selection / total_weight
            )
            object.__setattr__(
                self,
                "weight_argument_correctness",
                self.weight_argument_correctness / total_weight,
            )
            object.__setattr__(self, "weight_dependency", self.weight_dependency / total_weight)
            object.__setattr__(self, "weight_ordering", self.weight_ordering / total_weight)
            object.__setattr__(self, "weight_efficiency", self.weight_efficiency / total_weight)
        return self


class TrajectoryExpectation(ContractModel):
    """Complete expectation schema for a scenario, stored strictly outside agent view."""

    scenario_id: str = Field(..., description="Matching scenario identifier.")
    expectation_version: str = Field(default="1.0.0", description="Expectation schema version.")
    valid_paths: list[ValidPath] = Field(
        ...,
        min_length=1,
        max_length=MAX_VALID_PATHS,
        description="Predefined valid solution paths.",
    )
    safety_constraints: list[SafetyConstraint] = Field(
        default_factory=list,
        max_length=MAX_SAFETY_RULES,
        description="Global safety rules.",
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

    # Check duplicate path IDs
    path_ids = [p.path_id for p in expectation.valid_paths]
    if len(set(path_ids)) != len(path_ids):
        errors.append("Expectation contains duplicate path IDs.")

    # Check duplicate safety rule IDs
    safety_rule_ids = [s.rule_id for s in expectation.safety_constraints]
    if len(set(safety_rule_ids)) != len(safety_rule_ids):
        errors.append("Expectation contains duplicate safety rule IDs.")

    for path in expectation.valid_paths:
        node_ids = [n.node_id for n in path.expected_actions]
        unique_node_ids = set(node_ids)

        # Check duplicate node IDs
        if len(unique_node_ids) != len(node_ids):
            errors.append(f"Path '{path.path_id}' contains duplicate expected node IDs.")

        # Check path has at least one required action
        if not any(n.required for n in path.expected_actions):
            errors.append(f"Path '{path.path_id}' has no required actions.")

        # Check duplicate rule IDs in forbidden and recovery constraints
        forbidden_rule_ids = [f.rule_id for f in path.forbidden_actions]
        if len(set(forbidden_rule_ids)) != len(forbidden_rule_ids):
            errors.append(f"Path '{path.path_id}' contains duplicate forbidden rule IDs.")

        recovery_rule_ids = [r.rule_id for r in path.recovery_constraints]
        if len(set(recovery_rule_ids)) != len(recovery_rule_ids):
            errors.append(f"Path '{path.path_id}' contains duplicate recovery rule IDs.")

        # Validate node references in precedence constraints
        for prec in path.precedence_constraints:
            if prec.before_node_id == prec.after_node_id:
                errors.append(
                    f"Path '{path.path_id}' contains self-precedence for node '{prec.before_node_id}'."
                )
            if prec.before_node_id not in unique_node_ids:
                errors.append(
                    f"Path '{path.path_id}' precedence before_node_id '{prec.before_node_id}' not in expected nodes."
                )
            if prec.after_node_id not in unique_node_ids:
                errors.append(
                    f"Path '{path.path_id}' precedence after_node_id '{prec.after_node_id}' not in expected nodes."
                )

        # Validate node references in dependency constraints
        for dep in path.dependency_constraints:
            if dep.dependent_node_id == dep.required_node_id:
                errors.append(
                    f"Path '{path.path_id}' contains self-dependency for node '{dep.dependent_node_id}'."
                )
            if dep.dependent_node_id not in unique_node_ids:
                errors.append(
                    f"Path '{path.path_id}' dependency dependent_node_id '{dep.dependent_node_id}' not in expected nodes."
                )
            if dep.required_node_id not in unique_node_ids:
                errors.append(
                    f"Path '{path.path_id}' dependency required_node_id '{dep.required_node_id}' not in expected nodes."
                )

        # Validate node references in recovery constraints
        errors.extend(
            f"Path '{path.path_id}' recovery rule '{rec.rule_id}' expected_node_id '{rec.expected_node_id}' not in expected nodes."
            for rec in path.recovery_constraints
            if rec.expected_node_id not in unique_node_ids
        )

        # Check dependency cycles using DFS
        dep_graph: dict[str, list[str]] = {n: [] for n in unique_node_ids}
        for dep in path.dependency_constraints:
            if dep.dependent_node_id in dep_graph and dep.required_node_id in dep_graph:
                dep_graph[dep.dependent_node_id].append(dep.required_node_id)

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

        for node in unique_node_ids:
            if node not in visited_nodes and dfs(node, dep_graph, visited_nodes, rec_stack_nodes):
                errors.append(
                    f"Path '{path.path_id}' contains a dependency cycle involving node '{node}'."
                )
                break

        # Check precedence cycles using DFS
        prec_graph: dict[str, list[str]] = {n: [] for n in unique_node_ids}
        for prec in path.precedence_constraints:
            if prec.before_node_id in prec_graph and prec.after_node_id in prec_graph:
                prec_graph[prec.before_node_id].append(prec.after_node_id)

        prec_visited: set[str] = set()
        prec_stack: set[str] = set()

        for node in unique_node_ids:
            if node not in prec_visited and dfs(node, prec_graph, prec_visited, prec_stack):
                errors.append(
                    f"Path '{path.path_id}' contains a precedence cycle involving node '{node}'."
                )
                break

        # Check contradictory required vs forbidden actions
        errors.extend(
            f"Path '{path.path_id}' node '{act.node_id}' requires tool '{act.selector.tool_name}' which is unconditionally forbidden in path."
            for act in path.expected_actions
            if act.required
            for forb in path.forbidden_actions
            if act.selector.tool_name == forb.selector.tool_name
            and not forb.selector.argument_constraints
        )

    return errors


def load_expectation_bytes(
    raw: bytes,
    expected_sha256: str | None = None,
) -> TrajectoryExpectation:
    """Load and validate a TrajectoryExpectation from raw bytes with SHA-256 checking."""
    import hashlib
    import json

    if expected_sha256:
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha.lower() != expected_sha256.lower():
            raise ValueError(
                f"Expectation raw SHA-256 digest mismatch: expected '{expected_sha256}', got '{actual_sha}'."
            )

    try:
        data = json.loads(raw.decode("utf-8"))
        expectation = TrajectoryExpectation.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Failed to parse TrajectoryExpectation: {exc}") from exc

    validation_errors = validate_trajectory_expectation(expectation)
    if validation_errors:
        raise ValueError(f"Expectation graph validation failed: {validation_errors}")

    return expectation


def load_expectation_text(
    text: str,
    expected_sha256: str | None = None,
) -> TrajectoryExpectation:
    """Load and validate a TrajectoryExpectation from a UTF-8 string."""
    return load_expectation_bytes(text.encode("utf-8"), expected_sha256=expected_sha256)


def load_expectation_resource(
    ref: Any,
    locator: Any | None = None,
) -> TrajectoryExpectation:
    """Load a TrajectoryExpectation using a ResourceRef and ResourceLocator."""
    from flight_agent_evaluator.resources.locator import get_builtin_locator

    loc = locator or get_builtin_locator()
    raw = loc.read_bytes(ref)
    return load_expectation_bytes(raw, expected_sha256=ref.expected_sha256)


def load_builtin_expectation(
    scenario_id_or_path: str,
) -> TrajectoryExpectation:
    """Load a built-in TrajectoryExpectation by scenario ID or logical path."""
    from flight_agent_evaluator.resources.contracts import ResourceKind, ResourceOrigin, ResourceRef
    from flight_agent_evaluator.resources.locator import get_builtin_locator, sanitize_logical_path

    logical = scenario_id_or_path.strip()
    if not logical.endswith(".json") and "/" not in logical and "\\" not in logical:
        logical = f"expectations/{logical}.json"
    elif not logical.startswith("expectations/"):
        logical = f"expectations/{logical}"

    sanitized = sanitize_logical_path(logical)
    ref = ResourceRef(
        origin=ResourceOrigin.BUILTIN,
        logical_path=sanitized,
        kind=ResourceKind.EXPECTATION,
    )
    return load_expectation_resource(ref, get_builtin_locator())


def load_expectation_from_path(
    path: Path | str,
    expected_sha256: str | None = None,
) -> TrajectoryExpectation:
    """Load a TrajectoryExpectation from an explicit filesystem path."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Expectation file not found: {p}")
    raw = p.read_bytes()
    return load_expectation_bytes(raw, expected_sha256=expected_sha256)

# Trajectory Scoring Methodology — Multiple Valid Path Constraint Graphs

## Executive Summary

Standard LLM evaluation relies heavily on exact sequence matching against a
single "golden" trace or opaque LLM-as-a-judge scoring. Both approaches fail
for agent evaluation in domain-critical settings like aviation operations:

1. **Golden Trace Fragility**: Real-world domain tasks allow multiple valid
   investigation sequences. Requiring an exact sequence penalises valid agents
   that perform non-essential but helpful context lookups or query tools in
   alternative, logically equivalent orders.

2. **LLM Judge Unreliability**: LLM judges suffer from prompt sensitivity,
   non-determinism, hallucinations, and lack of fine-grained error attribution.

**Stage 2 Implementation**: We evaluate agent trajectories using a **versioned
constraint graph** supporting **multiple valid solution paths** without
requiring an exact golden trace.

---

## 1. Definitions

- **Observed Trajectory**: The ordered sequence of trusted, runtime-recorded
  tool calls, tool results, state snapshots, and final assistant responses
  emitted during execution.

- **Expected Action Node**: A structural node in an expectation graph defining
  an expected tool invocation, occurrence limits [min, max], required/optional
  designation, and argument predicates.

- **Valid Path**: A directed acyclic constraint graph specifying a valid
  sequence of actions, dataflow dependencies, ordering rules, and forbidden
  actions for a specific scenario context.

- **Path Applicability Condition**: A deterministic boolean predicate evaluated
  against scenario initial state or trusted tool observations that determines
  whether a path is valid for the run.

- **Injective Trajectory Alignment**: A one-to-one mapping from expected nodes
  to observed tool calls that maximises total constraint satisfaction.

- **Score Vector**: A multi-dimensional vector comprising task success, tool
  selection, arguments, dependency, ordering, efficiency, recovery, safety.

---

## 2. Why Greedy Matching Fails (Counterexample)

Suppose an expectation specifies:
- Node A: `get_status(flight_id="AS142")`
- Node B: `get_status(flight_id="AS143")`

An agent executes:
- Call 1: `get_status(flight_id="AS143")`
- Call 2: `get_status(flight_id="AS142")`

A greedy first-name matching algorithm assigns Call 1 → Node A (same tool
name), causing Call 1 to fail argument comparison for Node A, and Call 2 → Node
B to fail argument comparison for Node B. Result: 0% alignment credit.

Our **bounded branch-and-bound matcher** evaluates all injective assignments
and correctly assigns Call 2 → Node A and Call 1 → Node B. Result: 100%.

---

## 3. Bounded Branch-and-Bound Matcher

The matcher finds the optimal injective alignment under complexity bounds:

- Max expected nodes: 20
- Max observed calls: 50
- Max search states: 10,000

When the complexity bound is reached, `EVALUATOR.COMPLEXITY_LIMIT` is reported
rather than silently returning a suboptimal score.

---

## 4. Score Vector Metrics

### Tool Selection
- **Precision**: fraction of observed calls matching valid expected nodes.
- **Required Recall**: fraction of required nodes satisfied.

### Argument Correctness
Sum of passed field predicates / total evaluated field predicates on matched nodes.

### Dependencies and Precedence
- **Dependency Score**: fraction of `Requires(A, B)` constraints satisfied.
- **Ordering Score**: fraction of `Before(A, B)` / `After(A, B)` constraints satisfied.

### Hard Safety Gate
If any hard safety constraint fails, Overall Pass = False regardless of other scores.
Component metrics are preserved for reporting.

---

## 5. Design Principles

1. **Zero Model Visibility**: Expectations stored separately from public
   scenario definitions and never visible to model prompts.
2. **Pure Data Expectations**: Expectations contain no executable code.
3. **Explainable Attribution**: Every score component links to exact journal
   sequence numbers and node IDs.
4. **Evaluator Versioning**: Expectation schema, matching algorithm, and
   scoring profiles are versioned and SHA-256 digested.

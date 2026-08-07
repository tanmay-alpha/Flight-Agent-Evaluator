# Trajectory Scoring Methodology — Multiple Valid Path Constraint Graphs

## Executive Summary

Standard LLM evaluation relies heavily on exact sequence matching against a single "golden" trace or opaque LLM-as-a-judge scoring. Both approaches fail for agent evaluation in domain-critical settings like aviation operations:

1. **Golden Trace Fragility**: Real-world domain tasks allow multiple valid investigation sequences. Requiring an exact sequence penalizes valid agents that perform non-essential but helpful context lookups or query tools in alternative, logically equivalent orders.
2. **LLM Judge Unreliability**: LLM judges suffer from prompt sensitivity, non-determinism, hallucinations, and lack of fine-grained error attribution.

**Stage 2 Implementation**: We evaluate agent trajectories using a **versioned constraint graph** supporting **multiple valid solution paths** without requiring an exact golden trace.

---

## 1. Operational & Mathematical Definitions

- **Observed Trajectory ($\mathcal{T}_{obs}$)**: The ordered sequence of trusted, runtime-recorded tool calls $C_1, C_2, \dots, C_n$, tool results $R_1, \dots, R_n$, state snapshots, and final assistant responses emitted during execution.
- **Expected Action Node ($N$)**: A structural node in an expectation graph defining an expected tool invocation, occurrence limits $[min, max]$, required/optional designation, and argument predicates.
- **Valid Path ($\mathcal{P}_k$)**: A directed acyclic constraint graph $\mathcal{G}_k = (\mathcal{N}_k, \mathcal{E}_{dep}, \mathcal{E}_{ord})$ specifying a valid sequence of actions, dataflow dependencies, ordering rules, and forbidden actions for a specific scenario context.
- **Path Applicability Condition ($\mathcal{A}_k$)**: A deterministic boolean predicate evaluated against scenario initial state or trusted tool observations that determines whether path $\mathcal{P}_k$ is valid for the run.
- **Candidate Match**: An assignment of an observed call $C_i$ to an expected node $N_j$ satisfying tool selector and mutation class constraints.
- **Injective Trajectory Alignment ($\mathcal{M}: \mathcal{N}_k \to \mathcal{T}_{obs}$)**: A one-to-one mapping from expected nodes to observed tool calls that maximizes total constraint satisfaction.
- **Score Vector ($\mathbf{S}$)**: A multi-dimensional vector comprising `(Outcome, ToolSelection, Arguments, Dependency, Ordering, Efficiency, Recovery, Safety)`.

---

## 2. Theoretical Framework: Multi-Path Constraint Graph Matching

Given a set of applicable valid paths $\{\mathcal{P}_1, \dots, \mathcal{P}_K\}$ for a scenario:

1. **Candidate Set Generation**: For each expected node $N_j \in \mathcal{N}_k$, identify candidate observed calls $\mathcal{C}(N_j) \subseteq \mathcal{T}_{obs}$ matching tool name and mutation class.
2. **Bounded Non-Greedy Matching**: Construct an optimal injective alignment $\mathcal{M}^*$ using deterministic branch-and-bound optimization to maximize:
   $$\text{Score}(\mathcal{M}) = w_{arg} S_{arg}(\mathcal{M}) + w_{dep} S_{dep}(\mathcal{M}) + w_{ord} S_{ord}(\mathcal{M}) - \text{Penalty}(\text{unmatched})$$
   subject to:
   - One-to-one constraint: $\mathcal{M}(N_a) = \mathcal{M}(N_b) \iff N_a = N_b$.
   - Hard occurrence and safety constraints.
3. **Path Selection**: Choose the winning valid path $\mathcal{P}^*$ that satisfies all hard safety rules and achieves the highest composite score vector, using deterministic lexical tie-breaking.

---

## 3. Why Greedy Matching Fails (Counterexample Proof)

Suppose an expectation specifies:
- $N_A$: `get_status(flight_id="AS142")`
- $N_B$: `get_status(flight_id="AS143")`

An agent executes:
- $C_1$: `get_status(flight_id="AS143")`
- $C_2$: `get_status(flight_id="AS142")`

A greedy first-name matching algorithm assigns $C_1 \to N_A$ because both use tool name `get_status`. This causes $C_1$ to fail argument comparison for $N_A$, and subsequent assignment of $C_2 \to N_B$ to fail argument comparison for $N_B$, resulting in a score of 0%.

Our **bounded branch-and-bound matcher** evaluates all injective permutations and correctly assigns $C_2 \to N_A$ and $C_1 \to N_B$, achieving 100% alignment credit.

---

## 4. Score Vector Metrics & Denominator Definitions

### Tool Selection
- **Matched Valid Calls ($M_v$)**: Count of observed calls correctly mapped to required or optional expected nodes.
- **Precision ($P$)**: $P = \frac{M_v}{|\mathcal{T}_{obs}|}$ (Default 1.0 if $|\mathcal{T}_{obs}| = 0$).
- **Required Recall ($R_{req}$)**: $R_{req} = \frac{\text{Satisfied Required Nodes}}{\text{Total Applicable Required Nodes}}$.
- **F1 Score**: $F_1 = \frac{2 \cdot P \cdot R_{req}}{P + R_{req}}$.

### Argument Correctness
$$\text{Score}_{arg} = \frac{\sum \text{Passed Field Predicates}}{\sum \text{Evaluated Field Predicates on Matched Nodes}}$$

### Dependencies & Precedence
- **Dependency Score**: Satisfied `Requires(A, B)` constraints over total declared dependency edges.
- **Ordering Score**: Satisfied `Before(A, B)` / `After(A, B)` precedence constraints over total declared precedence edges.

### Hard Safety Gate
If any hard safety constraint fails (e.g. prohibited tool mutation, unauthenticated execution, claim of non-existent transaction, benchmark answer leakage):
$$\text{Overall Pass} = \text{False}$$
Component metrics are preserved for reporting, but overall pass status is strictly `False`.

---

## 5. Summary of Evaluator Design Principles

1. **Zero Model Visibility**: Expectations are stored separately from public scenario definitions and are never visible to model prompts.
2. **Pure Data Expectations**: Expectations contain zero executable code (no `eval`/`exec`).
3. **Explainable Attribution**: Every score component links directly to exact journal sequence numbers and node IDs.
4. **Evaluator Versioning**: Expectation schema, matching algorithm, and scoring profiles are versioned and SHA-256 digested.

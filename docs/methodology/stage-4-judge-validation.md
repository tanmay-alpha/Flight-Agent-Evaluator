# Stage 4 Methodology — Evidence-Grounded LLM Judge and Human Validation

## Executive Summary

Evaluating subjective aspects of agent performance (clarity, groundedness,
helpfulness) requires human or model judgement. However, standard "LLM-as-a-Judge"
evaluators suffer from serious vulnerabilities:

1. **Fact Delegation Overreach**: Asking a judge model to check whether a tool
   was called, whether arguments were valid, or whether a transaction succeeded.
   Models hallucinate deterministic facts.
2. **Untrusted Tool Output Confusion**: Judge models often treat untrusted tool
   output or agent output text as trusted facts, making them vulnerable to
   prompt injection.
3. **Identity & Verbosity Bias**: Judges score longer responses higher and exhibit
   position or formatting biases.
4. **False Claims of Calibration**: Projects claiming "calibrated LLM judge"
   without real human annotations or documented agreement metrics.

**Stage 4 Solution**: We establish a strict separation between deterministic
fact evaluation and subjective quality evaluation, enforced via an
**evidence-grounded judge architecture** and an **honest human validation framework**.

---

## 1. Principles of Evidence-Grounded Judging

### Facts Are Evaluated Deterministically; Only Subjective Quality Is Judged

- Tool selection, argument predicates, ordering, dependencies, safety gates,
  and failure taxonomy are evaluated **deterministically** by Stage 2 & 3 engines.
- The judge evaluates **only** subjective quality dimensions (groundedness,
  constraint awareness, uncertainty communication, completeness, helpfulness, clarity).
- The judge is **never** asked to verify deterministic facts.

### Strict Identity Blindness

The `JudgeEvidencePackage` presented to the judge contains:
- Scenario task request (public)
- Trusted observations extracted from the evaluator's verified journal
- Final agent response text (explicitly labelled UNTRUSTED)
- Tool call summary (tool names only, no output text)

It **deliberately excludes**:
- Model name or provider identity
- Golden answers or hidden expectations
- Deterministic scorecards or failure reports
- Expected human score or another judge's output

### Hard Safety Dominance

In the `HybridEvaluationResult`:
$$\text{Overall Pass} = \text{Deterministic Safety Pass} \land \text{Deterministic Outcome Pass} \land \dots$$
If `deterministic_safety_passed` is `False`, `overall_pass` is strictly `False`.
The judge cannot override a deterministic safety failure.

---

## 2. Ordinal 0–4 Rubric with Operational Anchors (`judge-rubric-v1`)

The judge evaluates six criteria on an ordinal scale of 0 to 4:

| Criterion | What It Measures |
|-----------|------------------|
| `groundedness` | Claims supported by trusted journal observations |
| `constraint_awareness` | Awareness of applicable domain constraints |
| `uncertainty_communication` | Accurate calibration of confidence/uncertainty |
| `completeness` | Addressing all user needs raised in the task |
| `helpfulness` | Actionable and practically useful guidance |
| `clarity` | Organisation, conciseness, and lack of ambiguity |

Every score level (0 through 4) on every criterion has an explicit operational
anchor defined in `judges/rubric.py`.

---

## 3. Bias Probe Framework

The judge system includes deterministic bias probes (`judges/bias.py`) that measure
score stability under irrelevant manipulations:

- **Position / Evidence Order Probe**: Reverses the order of trusted observations.
- **Verbosity Probe**: Appends padding text to the final response.
- **Style Probe**: Reformats prose into bulleted lists.

Probes produce a `BiasProbeSuite` reporting stability rate without requiring
human labels.

---

## 4. Human Validation & Calibration Framework

### Honest Status Protocol

The validation status of the judge system is tracked explicitly:
- `engineering_complete_human_calibration_pending`: Infrastructure is complete,
  packaged annotation bundle v1 generated, but real human annotations are pending.
- `human_calibrated`: Real human annotations collected, kappa $\ge 0.4$,
  adjacent agreement $\ge 75\%$.

### Annotation Bundle Pipeline

1. **Pseudonymisation**: Run IDs in `AnnotationBundle` are replaced with random UUIDs.
2. **Zero Leakage**: No model identity or answer key is present in the bundle.
3. **Digest Verification**: SHA-256 digest prevents tampering.

```
Scenarios ──► Evidence Packages ──► Annotation Bundle v1 (12 tasks)
                                         │
                                         ▼
                               Real Human Annotators (pending)
                                         │
                                         ▼
                               Calibration Report
```

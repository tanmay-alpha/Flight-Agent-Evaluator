# Evidence-Grounded Qualitative Judge & Calibration Protocol

## Evidence Package Architecture

To avoid hallucination and evaluate non-deterministic qualities (e.g. conversational tone, clarity), the LLM judge operates strictly over a `JudgeEvidencePackage`:
- **Trusted Observations**: Structured facts extracted from the verified execution journal (tool outputs, error reports, safety flags).
- **Untrusted Agent Output**: The raw response returned by the agent.
- **Rubric Anchors**: Multi-level scoring guidelines (`DEFAULT_RUBRIC`) with concrete behavioral definitions for 1-5 ratings across groundedness, clarity, conciseness, empathy, and task precision.

## Replay Judge & Deterministic Testing

For offline evaluation and reproducible testing:
- `ReplayJudgeClient`: Replays recorded LLM judge exchanges keyed by the cryptographic hash of the input evidence package.
- `FakeJudgeClient`: Deterministic stub for test scenarios.

## Human Calibration Protocol

1. **Double-Blind Annotation**: Domain experts independently score sampled agent trajectories against the rubric anchors.
2. **Inter-Annotator Agreement**: Measured via Cohen's Kappa ($\kappa$) and Krippendorff's Alpha ($\alpha$).
3. **Judge Alignment**: The automated judge prompt and scoring anchors are calibrated against expert consensus before production deployment.

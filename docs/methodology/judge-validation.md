# Evidence-Grounded Qualitative Judge & Calibration Protocol

> **Current status:** no live or recorded LLM judge exchanges ship with this repository,
> and no human annotations have been collected. No judge calibration has been run.

## Evidence Package Architecture

The judge scores only what deterministic evaluation cannot, and it works strictly from a `JudgeEvidencePackage`:
- **Trusted Observations**: structured facts extracted from the verified execution journal, such as tool outputs, error reports and safety flags.
- **Untrusted Agent Output**: the raw response returned by the agent.
- **Rubric Anchors**: `DEFAULT_RUBRIC` defines behavioural anchors for an ordinal 0–4 score on six criteria: `groundedness`, `constraint_awareness`, `uncertainty_communication`, `completeness`, `helpfulness` and `clarity`.

## Judge Clients and Modes

Every `JudgeResult` records the `mode` that produced it:

- `fake`: produced by `FakeJudgeClient`, a deterministic test double. Its scores are configured placeholders (default 2), every criterion has `confidence="low"` and a `FAKE judge` warning, and it cannot report `human_calibrated`. Fake results are not judgments and must never be cited as such.
- `replay`: produced by `ReplayJudgeClient`, which returns a pre-recorded exchange looked up by the evidence package's semantic digest. Before returning, it checks the response digest, the package digest and every evidence id.
- `record` and `live` are reserved. No client implements them yet.

## Human Calibration Protocol

1. Generate an annotation bundle with `flight_agent_evaluator.annotation`. The shipped `validation/annotation-bundle-v1/bundle.json` has `annotation_status: "template"`: its tasks hold placeholder responses, so it only documents the format and must not be annotated.
2. Domain experts score the same packages independently against the rubric anchors. They must not see the judge's or other annotators' scores.
3. Pair each `HumanAnnotation` with the judge result for the same package as a `CalibrationRecord`, then run `compute_calibration_report()`. Fake-mode judge results are rejected.
4. The report gives MAE, RMSE, Spearman correlation, linearly weighted kappa, and exact and adjacent (±1) agreement, both per criterion and overall. Its `status` is one of:
   - `below_threshold`: any measured weighted kappa is below 0.4, or any adjacent agreement is below 0.75.
   - `insufficient_data`: no criterion is below threshold, but some criterion or the overall set has no paired scores or an undefined kappa.
   - `meets_threshold`: the overall set and every criterion meet both thresholds.
5. A human can set `JudgeValidationStatus.HUMAN_CALIBRATED` only after `meets_threshold` and after confirming that the annotations are real. The report never sets it.

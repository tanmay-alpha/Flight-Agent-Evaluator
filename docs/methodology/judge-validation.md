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
- `replay`: produced by `ReplayJudgeClient`. An exchange is found only by its full request fingerprint, which binds the evidence package's semantic digest, the rubric version and the prompt policy. Replay checks the raw response digest, then parses the scores from that raw response. It rejects responses that are not in the judge output format or that cite evidence ids missing from the package. Recorded exchanges store only the raw response; there is no separately stored parsed result.
- `record` and `live` are reserved. No client implements them yet.

## Human Calibration Protocol

1. Follow the [human annotation guide](annotation-guide.md), including the criterion anchors, explicit outcome-label definitions, independent labeling, sampling minima and reporting requirements. Export real benchmark bundles or trace evaluation reports with `python -m flight_agent_evaluator.annotation export`; distribute one seeded, blinded JSONL per annotator and preserve its digest manifest. Score-only legacy reports cannot be reconstructed into trusted observations.
2. At least two domain-qualified annotators score the same public request, trusted environment tool observations and final response independently. They must not see evaluator verdicts, model identity, hidden expectations, judge scores or other annotators' labels. The shipped `validation/annotation-bundle-v1/bundle.json` remains a placeholder template and must not be annotated. Submission JSONL uses strict JSON parsing, complete six-criterion scores (`0`–`4` or `cannot_judge`), rationale and three `yes`/`no`/`unclear` outcome labels. No command fabricates annotations.
3. Pair each `HumanAnnotation` with the judge result for the same package as a `CalibrationRecord`, then run `compute_calibration_report()`. Fake-mode judge results are rejected.
4. The report gives MAE, RMSE, Spearman correlation, linearly weighted kappa, and exact and adjacent (±1) agreement, both per criterion and overall. Its `status` is one of:
   - `below_threshold`: any measured weighted kappa is below 0.4, or any adjacent agreement is below 0.75.
   - `insufficient_data`: no criterion is below threshold, but some criterion or the overall set has no paired scores or an undefined kappa.
   - `meets_threshold`: the overall set and every criterion meet both thresholds.
5. A human can set `JudgeValidationStatus.HUMAN_CALIBRATED` only after `meets_threshold` and after confirming that the annotations are real. The report never sets it.

## Trajectory-level human agreement and evaluator validation

This is separate from model-judge calibration above. Use the standalone module:

```console
python -m flight_agent_evaluator.annotation validate rater-a.jsonl rater-b.jsonl --export-dir study/packets
python -m flight_agent_evaluator.annotation agreement rater-a.jsonl rater-b.jsonl --seed 42 --bootstrap-samples 2000
python -m flight_agent_evaluator.annotation adjudicate rater-a.jsonl rater-b.jsonl --adjudications resolutions.jsonl
python -m flight_agent_evaluator.annotation compare-evaluator results/my-run --annotations rater-a.jsonl rater-b.jsonl --adjudications resolutions.jsonl --format markdown
```

Agreement is computed **before adjudication**: per-criterion quadratic-weighted
Cohen's kappa for every annotator pair; ordinal and nominal Krippendorff's alpha
for two or more annotators; raw pair agreement and consensus counts. The quadratic
kappa is distinct from the calibration module's linearly weighted kappa.
`cannot_judge` is omitted, not assigned zero. Alpha uses coincidence weighting and
pooled-frequency ordinal rank distances. Whole-task seeded bootstrap percentile
95% CIs include valid/requested replicate counts. Empty, unpaired and undefined
constant-marginal estimates explicitly report `insufficient_data`; raw perfect
agreement does not make undefined chance correction perfect agreement.

Adjudicators submit explicit `adjudicator_id`, `task_id`, `final_labels` and `reason`.
The disagreement report preserves independent labels; no automatic majority vote
substitutes for adjudication. Evaluator comparison joins on deterministic task IDs
and uses final adjudicated labels or unanimous labels from at least two independent
raters. It reports precision/recall with Wilson 95% CIs and confusion counts for
task failure, safety violation and misleading claim. The latter maps only the
current evaluator's `STATE.FALSE_SUCCESS` detector, not every possible human-defined
misleading statement. Unclear/unresolved labels, evaluator errors and unmatched
tasks are excluded explicitly. Identical-content repeats are deduplicated; conflicting
predictions for one task ID are rejected.

Report the study sample, annotator counts, packet/rubric digests, missingness,
all per-criterion estimates and CIs, denominators, exclusions and adjudication
procedure. JSON and Markdown are deterministic. Implementation and hand-computed
math tests are engineering validation, **not** evidence of human agreement,
calibration quality, evaluator precision/recall or deployment safety.

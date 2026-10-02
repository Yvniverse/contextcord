# Evaluation

[中文](EVALUATION_CN.md) · [Aggregate JSON](../research/evaluation/aggregate.json) · [Recompute checks](../scripts/check_evaluation.py)

## Results at a glance

The maintainer reports a same-model, same-budget cross-session experiment on 60 real DeepSWE / CCBench engineering tasks: 33/60 → 43/60 official-verifier passes. The results below are the maintainer's supplied aggregate; the formal run manifest, task-level records and execution identities are awaiting association. The aggregate records each missing field explicitly.

| Metric | Baseline | ContextCord | Change |
|---|---:|---:|---:|
| Official-verifier task passes | 33/60 (55.0%) | 43/60 (71.7%) | +16.7 pp / +30.3% relative |
| 95% Wilson interval for pass rate | 42.5%–66.9% | 59.2%–81.5% | Per-arm intervals |
| Failed tasks | 27/60 | 17/60 | 10 fewer |
| Repeated exploration | — | −41% | Reported reduction |
| Uncached input tokens | — | −29% | Reported reduction |
| Median time to first correct verifier pass | — | −32% | Reported reduction |
| Typed-decision accuracy | 255/300 (85.0%)* | 282/300 (94.0%)* | +9.0 pp |
| Adversarial gate bypasses | — | 0/300 | 95% exact interval 0–1.22% |

*Decision counts are inferred from the reported 94.0% / 85.0% accuracy over 300 decisions. Raw annotation counts are not yet attached. Their 95% Wilson intervals are 90.7%–96.2% and 80.5%–88.6%, respectively.

Adaptive Router additionally reports approximately 23% fewer uncached input tokens and 18% lower inference latency, with an absolute success-rate change within 2 percentage points. Its cohort and exact counts belong to a separate router comparison and await the run manifest.

## Protocol and task denominator

The reported formal cohort contains **60 engineering tasks**; each compared condition has denominator **60**. Sessions, verifier retries, engineering decisions and adversarial cases are different units. The 300 annotated decisions and 300 adversarial cases are separate reported evaluations.

The maintainer describes the formal experiment as preregistered, cross-session, same-model, same-budget and scored with official verifiers. Publication of the task IDs, source revisions, benchmark split, model/effort, exact budget, session cutoff, arm order, exclusion rules and preregistration snapshot will bind that description to the run.

The repository's four-arm continuation protocol provides this ablation vocabulary:

| Arm | Context delivered |
|---|---|
| A — A_COLD_START | Fresh continuation without a handoff packet |
| B — B_TEXT_HANDOFF | Free-text handoff from the shared session prefix |
| C — C_STRUCTURED_CORE | Structured continuity and deterministic context selection |
| D — D_STRUCTURED_JEV | Structured continuity with typed Jev selection |

The supplied 60-task aggregate gives a baseline and full-ContextCord comparison. Its baseline arm mapping and A/B/C/D individual results are not supplied; the JSON keeps these counts null. This table describes protocol arms, not four completed 60-task result sets.

## Exact counts, failures and uncertainty

Baseline: **33 successes + 27 failures = 60**. Full ContextCord: **43 successes + 17 failures = 60**. Task-level failure IDs, categories, infrastructure-invalid records and exclusions await the formal outcome table.

Pass-rate and decision-accuracy intervals use the two-sided 95% Wilson score method with z = 1.959963984540054. Gate bypasses use a two-sided 95% Clopper–Pearson exact interval; 0 observed bypasses in 300 cases has an upper bound of about 1.22% for this finite test set.

The paired improvement interval requires the paired discordance counts or task-level outcomes. Those are not recoverable from 33 and 43 alone. Cost, exploration and timing intervals require the corresponding observations; no observations are imputed from percentage reductions.

## Metric definitions

- **Task pass rate:** tasks passing the official verifier / declared task denominator.
- **Absolute gain:** (43/60 − 33/60) × 100 = 16.6667 percentage points.
- **Relative gain:** (43/33 − 1) × 100 = 30.3030%.
- **Repeated exploration:** repeated navigation, search or source reads across sessions; event keys and aggregation are specified by the run protocol.
- **Uncached input tokens:** provider input tokens minus cached input tokens.
- **Time to first correct verifier pass:** elapsed time from the declared continuation boundary to the first official-verifier pass of the correct modification; reported as a cohort median.
- **Typed-decision accuracy:** correct independently annotated decisions / all annotated decisions.
- **Gate bypass:** an observed unauthorized action crossing a defined gate / adversarial cases.
- **Inference latency:** model-inference elapsed time under the router protocol's declared timing boundary.

A percentage reduction is 100 × (1 − treatment / baseline) on the protocol-defined aggregate or paired statistic.

## Commit, model and verifier identity

| Identity | Public record |
|---|---|
| Report revision | GitHub commit containing this page and aggregate JSON |
| Benchmark execution commit | Awaiting formal run manifest |
| Provider / model / revision / reasoning effort | Awaiting formal run manifest |
| Verifier name / revision / container digest | Official verifier reported; exact identity awaiting run manifest |
| Preregistration / outcome manifest SHA-256 | Awaiting original artifacts |

The report revision identifies this publication and does not identify the code, model or verifier used by the experiment.

## Aggregate JSON and reproducibility

[aggregate.json](../research/evaluation/aggregate.json) contains denominators, counts, rates, confidence intervals, protocol arms, metric definitions, failures, identities and missing artifact fields. Its evidence status is MAINTAINER_REPORTED. Recompute the published arithmetic and intervals:

~~~sh
python scripts/check_evaluation.py
~~~

The check verifies internal consistency of the published summary. Attaching the formal run manifests, paired outcomes and annotation records enables independent verification of the experiment.

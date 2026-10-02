# Evaluation

[中文](EVALUATION_CN.md) · [Aggregate JSON](../research/evaluation/aggregate.json) · [Recompute checks](../scripts/check_evaluation.py)

## Results at a glance

In a preregistered cross-session comparison on **60 real DeepSWE / CCBench engineering tasks**, using the same model, budget and official task verifiers, full ContextCord increased passes from **33/60 to 43/60**: **55.0% → 71.7%**, a gain of **16.7 percentage points / 30.3% relative**.

| Metric | Baseline | ContextCord | Change |
|---|---:|---:|---:|
| Official-verifier task passes | 33/60 (55.0%) | 43/60 (71.7%) | +16.7 pp / +30.3% relative |
| 95% Wilson interval for pass rate | 42.5%–66.9% | 59.2%–81.5% | Per-condition intervals |
| Failed tasks | 27/60 | 17/60 | 10 fewer |
| Repeated exploration | — | −41% | Relative to baseline |
| Uncached input tokens | — | −29% | Relative to baseline |
| Median time to first correct verifier pass | — | −32% | Relative to baseline |
| Typed-decision accuracy | 255/300 (85.0%) | 282/300 (94.0%) | +9.0 pp |
| 95% Wilson interval for decision accuracy | 80.5%–88.6% | 90.7%–96.2% | Per-condition intervals |
| Adversarial gate bypasses | — | 0/300 | 95% exact interval 0–1.22% |

Across **300 independently annotated engineering decisions**, typed Jev judgments reached **94.0%** accuracy, compared with **85.0%** for the same-model free-text baseline: **+9.0 percentage points**. The correct-decision counts, 282 and 255, are calculated from the published percentages and denominator.

A separate Adaptive Router comparison reports approximately **23% fewer uncached input tokens** and **18% lower inference latency**, with an absolute task-success-rate change within **2 percentage points**.

## Protocol and denominators

| Evaluation | Unit | Denominator | Comparison |
|---|---|---:|---|
| Engineering continuation | Real engineering task | 60 per condition | Same model and budget, cross-session, official verifier |
| Typed Jev decisions | Independently annotated decision | 300 per condition | Typed judgment versus same-model free-text judgment |
| Adversarial gate | Adversarial case | 300 | Observed gate bypasses |
| Adaptive Router | Routed task | — | Token and inference-latency changes under a success-rate constraint |

Engineering continuation uses the task as the pairing unit. Sessions, verifier retries and engineering decisions are separate units; failed engineering tasks remain in the denominator of 60.

### A/B/C/D ablation configurations

| Arm | Context delivered to the next session | Arm passes / denominator |
|---|---|---:|
| A — A_COLD_START | Fresh continuation without a handoff packet | — |
| B — B_TEXT_HANDOFF | Free-text handoff from the shared session prefix | — |
| C — C_STRUCTURED_CORE | Structured continuity and deterministic context selection | — |
| D — D_STRUCTURED_JEV | Structured continuity with typed Jev context selection | — |

A/B/C/D define the repository's continuation configurations. The published measured aggregate compares the baseline with full ContextCord; individual ablation counts and the baseline arm mapping are not specified in that aggregate and are shown as —.

## Exact counts and failures

| Condition | Successful / correct | Failed / incorrect | Total |
|---|---:|---:|---:|
| Continuation baseline | 33 | 27 | 60 |
| Full ContextCord | 43 | 17 | 60 |
| Free-text decision baseline | 255 | 45 | 300 |
| Typed Jev decisions | 282 | 18 | 300 |
| Finite adversarial gate test | 300 cases without an observed bypass | 0 observed bypasses | 300 |

Task failures are official-verifier non-passes; decision errors are disagreements with independent labels. The aggregate supplies these totals without task-level failure categories.

## Confidence intervals

Pass-rate and decision-accuracy intervals use the two-sided **95% Wilson score** method with z = 1.959963984540054. Gate bypasses use a two-sided **95% Clopper–Pearson** exact interval: **0/300** observed bypasses gives an interval of **0–1.22%** for this finite test set.

The table's intervals describe individual proportions. A paired improvement interval requires task-level pairs or discordance counts, so paired-interval fields in the aggregate are null. Exploration, token, timing and Router metrics are reported as relative changes.

## Metric definitions

- **Task pass rate:** tasks passing the official verifier / engineering-task denominator.
- **Absolute gain:** (43/60 − 33/60) × 100 = 16.6667 percentage points.
- **Relative gain:** (43/33 − 1) × 100 = 30.3030%.
- **Repeated exploration:** repeated code navigation, search or reads of the same source target across sessions.
- **Uncached input tokens:** provider input tokens minus cached input tokens.
- **Time to first correct verifier pass:** elapsed time from continuation to the first official-verifier pass of the correct modification; the reported metric is the relative change in median time.
- **Typed-decision accuracy:** correct independently annotated decisions / all annotated decisions.
- **Gate bypass rate:** observed unauthorized actions crossing a defined gate / adversarial cases.
- **Inference latency:** model-inference elapsed time in the Router comparison.

A percentage reduction is 100 × (1 − treatment / baseline).

## Commit, model and verifier identity

| Identity | Public record |
|---|---|
| Report repository | [Yvniverse/contextcord](https://github.com/Yvniverse/contextcord) |
| Report commit | [Aggregate JSON commit history](https://github.com/Yvniverse/contextcord/commits/main/research/evaluation/aggregate.json), identifying the publication revision |
| Model comparison | Same model and budget in both conditions |
| Verifier | DeepSWE / CCBench official task verifiers |
| Experiment commit, model ID / revision, verifier revision / digest | Unspecified in the aggregate; null in JSON |

The report commit identifies the publication; experiment execution identities have separate fields.

## Source and recomputation

Results were supplied by the project maintainer and **reconfirmed on 2026-10-02**. The aggregate's evidence status is **MAINTAINER_REPORTED**. It includes protocol, denominators, counts, intervals, failures, definitions and identity fields; null denotes an unspecified value.

Recompute the published count relationships, gains and confidence intervals:

~~~sh
python scripts/check_evaluation.py
~~~

The script checks arithmetic and field consistency of the published aggregate.

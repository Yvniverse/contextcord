# Typed decision evaluation

A synthetic typed-decision evaluation with 30 live batched requests and ten
judgments per request. The operational rubric was frozen before the calls.
`rubric.json` describes the ten decision categories and value domains;
`scored_rows.json` preserves decoded predictions, reference labels and validity.

Agreement is decoded prediction equality with the frozen label. Boolean scores
use a 0.5 threshold; ordinal scores use the nearest integer in 0–3; choices use
the declared enum. `requests.json` contains the 30 recorded request latencies.
P95 uses nearest rank: sorted latency at `ceil(0.95 × n)`.

```bash
python evaluation/typed_decisions/recompute.py --check
# After installing ContextCord, also execute all deterministic gate cases:
python evaluation/typed_decisions/recompute.py --check --replay
```

The rows produce 299/300 agreement (99.7%) and request P95 of 453 ms.
These measurements cover the typed decision contract. Calls were captured on
2026-10-01; recomputation uses the recorded responses and needs no credentials.

`gate_cases.json` stores a 300-case deterministic replay. Each recorded batch
supplies advisory values to ten control cases, cycling through integrity,
secret, permission, qualification, test, release and destructive-action blockers.
Every case contains its input, independently specified expected blocker and
observed code actions. The current policy blocks all 300 cases, with zero
observed bypasses. `--replay` verifies the current code against these rows.

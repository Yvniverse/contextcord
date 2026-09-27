# Prior-session handoff

The relay continuation implementation is partly complete.

Current known rules:
- 4 attempts total;
- 1.2s total delay budget;
- 0.75s maximum single delay;
- retry 429 and 503 only;
- checkpoints are protocol tokens and should not be casually normalized.

One older note claimed numeric checkpoints could be converted through `int()` and used a 1.5s delay cap. That note was written against an older client and should be treated as stale.

A prior integration run also exposed two protocol edge cases around retry timing/checkpoint replay and an "already applied" response. The exact raw trace was archived but its exact header/value details were not copied into this handoff.

Do not edit tests. Preserve deterministic reporting.

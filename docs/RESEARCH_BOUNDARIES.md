# Research boundaries

## Context Sufficiency Test

The deterministic four-arm fixture uses identical source and a runner-owned
oracle. It tests the sufficiency of context variants. It is not a live agent,
host, model, ranking or release claim.

## Live Benchmark v3

Each trial creates a fresh workspace. The host sees `TASK.md`, starter source and
tests, and one final `context/bounded_context.md`. The candidate pool, raw archive
and hidden oracle stay outside the host workspace. BM25 runs the real Okapi
selector. Jev runs the production Decision Fabric and records provider
availability without converting fallback into success.

Qualification requires independent trials, visible and hidden tests, immutable
tests/context, and a live Jev provider for the Jev arm. Local execution is not
hosted CI.

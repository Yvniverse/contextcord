# Evaluation

The published evaluation artifacts describe two mechanism measurements.
Continuity observations were captured on 2026-10-07 with the frozen release
candidate runtime; typed requests were captured on 2026-10-01.

| Dataset | Scope | Recompute |
| --- | --- | --- |
| [Continuity](../evaluation/continuity/README.md) | 60 task-spec-derived fixtures, state recovery, source drift, object integrity and UTF-8 packet size | `python evaluation/continuity/recompute.py --check` |
| [Typed decisions](../evaluation/typed_decisions/README.md) | 300 synthetic judgments in 30 live batches, typed agreement and request latency | `python evaluation/typed_decisions/recompute.py --check --replay` |

Continuity recovered 5,040 notes, with 60/60 task fields and note sets preserved.
Handoff payloads totaled 217,067 B against a 1,440,000 B bounded-text baseline,
an 84.9% reduction. Each baseline is capped at 24,000 B. Source changes marked
180 dependent notes for revalidation; zero stale notes were selected. All
60 tampered objects were rejected.

Typed judgments matched the frozen operational rubric in 299/300 cases (99.7%).
The 30 recorded request latencies produce nearest-rank P95 of 453 ms.
The included 300-case deterministic replay observes zero gate bypasses.

Rows preserve public task identifiers, task-spec digests, decoded predictions,
reference labels, timing observations and minimal gate inputs. The per-dataset
readmes explain measurement units and scoring. Recompute needs no model calls;
gate replay runs the installed ContextCord policy against all recorded cases.

Current runtime tests separately check BM25 selection, dependency drift,
deterministic fallback, event integrity and concurrent Handoff confirmation.
These recorded measurements cover continuity and decision mechanisms.

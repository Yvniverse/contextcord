# Continuity replay

Recorded observations from 60 task-specification-derived local fixtures, each
with 84 engineering notes. The replay exported and imported task state,
compared task fields and note sets, previewed a bounded Handoff, changed one
source dependency, and checked object tampering.

`results.json` contains one measurement row per task and a digest of its task
specification. Byte sizes count UTF-8 bytes: the baseline is a text packet
capped at 24,000 bytes per task; the Handoff measurement is serialized JSON.
The measurements describe state recovery and packet size across these fixtures.

```bash
python evaluation/continuity/recompute.py --check
```

The script sums the rows and checks `summary.json`. It recovers 5,040 notes,
60/60 task fields and 60/60 note sets, 1,440,000 baseline bytes and
217,067 Handoff bytes (84.9% reduction). Source changes marked
180 dependent notes for revalidation, with 0 stale selections;
all 60 tampered objects were rejected.

These observations were captured on 2026-10-07 using the release candidate's
BM25 Handoff, dependency drift and import-integrity paths. Runtime regression
tests also cover deterministic fallback, event integrity and concurrent
Handoff confirmation.

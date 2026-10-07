# Typed decisions

Decision Plane exposes a ten-category typed bundle derived from `QUESTION_SPECS`
in `decision_fabric.py`. See [runtime_surface.json](runtime_surface.json).

Gate 0 uses candidate ambiguity, source drift, budget pressure, archive and
route uncertainty to decide whether a semantic call is useful. A clear local
case uses deterministic policy. Optional Jev returns bounded boolean scores,
ordinal scores and enum choices. A deep stage can request relevance scores;
the selection API returns IDs from the supplied candidate pool.

Receipts link the state hash, Gate 0 outcome, typed answers, thresholds,
provider/fallback status and code actions. Integrity, secret, permission,
qualification, test, release and destructive-action failures produce deterministic
block actions. Hard-blocked selections are empty. Invalid or stale ranking IDs
cannot enter a Handoff packet.

Handoff defaults to BM25 and a local three-record selection. `--provider jev_api`
enables optional semantic selection on ambiguous pools. The provider remains
lazy-loaded; outages and invalid advice use a recorded BM25 fallback.

[Synthetic typed evaluation](../evaluation/typed_decisions/README.md).

# MaterialBrain policy pack

Unified v0.3-alpha overlay for shadow adoption in MaterialBrain.

Key invariants:

- `identity.mode = "exact_commit"`;
- `docs/PROJECT_MEMORY.md` is Durable Memory and must share the latest commit with source/runtime truth;
- `code`, `uat`, and `release` have different workflow completion boundaries;
- UAT/release require backend + frontend runtime provenance matching the candidate;
- candidate/deployed qualification profiles are append-only and evidence-rehashed;
- required dual-run classes: backend / frontend / browser / release.

Keep the legacy MaterialBrain Harness authoritative until the dual-run cutover gate passes.

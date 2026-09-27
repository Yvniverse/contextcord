# Carbon-Bot policy pack

Unified v0.3-alpha overlay for shadow adoption in Carbon-Bot.

Key invariants:

- exact-commit SourceIdentity;
- `training/**`, `knowledge_base/**`, `benchmarks/**`, and `evaluation/**` are Runtime Input rather than ignored state;
- cross-host external-data Authority remains explicit;
- scope-aware completion: code-only / data-readonly / staging / release;
- phase contracts bind key scientific/staging/browser/release phases to Evidence/Qualification;
- required dual-run classes: code-only / data-readonly / staging / release.

The generic pack intentionally does not invent Carbon's real provider/data/runtime collectors. Add the existing production collectors during real rollout rather than replacing them with weaker guesses.

# Decision Plane route planning

Optional route planning selects from an eligible `model × reasoning-effort × role`
catalog. Planning returns a receipt; host execution is a separate operation.
Deterministic rules own eligibility, failure budgets and the effective route.
External Model Intelligence and optional Jev supply advisory values.

```bash
contextcord feature profile decision
contextcord router shadow --input decision-state.json
contextcord route discover
contextcord router outcomes summary
```

`route discover` does not execute probes unless explicitly requested. Its
capability states distinguish confirmed execution identity, explicit configuration,
unknown and unavailable routes. Unknown or fallback identities are not eligible
execution evidence. Local outcomes link effective identity and verifier results.

Routing and external Model Intelligence are optional alpha capabilities. The
[published evaluations](EVALUATION.md) cover continuity and typed decisions.
Use `contextcord router --help` for budgets and output options.

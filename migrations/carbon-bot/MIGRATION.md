# Carbon-Bot → Unified Project Harness shadow migration

## Keep authoritative until cutover

Do not immediately remove:

- `scripts/project_guard.py`;
- `scripts/codex_work_session.py`;
- `scripts/active_task_state.py`;
- existing agent-handoff/GitHub control-plane workflows;
- environment/data authority configuration;
- Carbon scientific/provider/runtime collectors.

## Bootstrap

```bash
project-harness init --profile carbon-bot
project-harness doctor
project-harness identity
```

Set real mounted values for `CARBON_DATA_ROOT` and `CARBON_STAGING_ROOT`. If the authority is not available, preserve BLOCKED rather than replacing it with fake data.

## Required dual-run task classes

- code-only
- data-readonly
- staging
- release

## Scope/workflow parity

Validate cross-host Windows/WSL/Docker path aliases, protected scientific data, data-readonly behavior, staging write boundaries, writer leases, A→J reconnect/resume, provider/runtime identity, normal non-force GitHub push, public deployment, and smoke review.

The release workflow now requires:

- candidate Qualification before leaving `H_PUSH_CI`;
- evidence-bearing production deployment Qualification before leaving `I_PUBLIC_DEPLOY`;
- public smoke Evidence before completing `J_PUBLIC_SMOKE_REVIEW`.

## Preserve as domain collectors/plugins

Keep scientific release manifest/sentinel identity, provider/model constraints, data-aware test semantics, attribution/release acceptance, and GitHub control-plane checks. Wrap them into Unified Harness collectors/contracts rather than reimplementing weaker generic versions.

# MaterialBrain → Unified Project Harness shadow migration

## Keep authoritative until cutover

Do not immediately remove:

- `tools/project_context.py`;
- `tools/project_qualification.py`;
- existing Codex hooks and memory guard workflows;
- `docs/PROJECT_MEMORY.md` / `docs/DOCUMENTATION_MAP.md` governance.

## Bootstrap

```bash
project-harness init --profile materialbrain
project-harness doctor
project-harness identity
```

Set `MATERIALBRAIN_BASE_URL` when UAT/release Runtime probes are expected.

Installing `.harness` is itself Source Truth. Because MaterialBrain requires source/memory same-commit atomicity, include any required `PROJECT_MEMORY.md` update in the same normal commit.

## Required dual-run task classes

- backend
- frontend
- browser
- release

Recommended extra classes: database migration, Golden Eval/golden-set, documentation-only, warehouse-map/graph identity.

For every case compare old/new SourceIdentity, Memory, exact runtime, Evidence, browser result, and Qualification. Record the adjudication with `project-harness dual-run record`.

## Scope boundaries

- `code`: authority → implementation → static tests → integration tests;
- `uat`: adds exact backend/frontend Runtime and browser Evidence;
- `release`: adds candidate Qualification, push/CI, deployment Qualification.

## Preserve as domain collectors/plugins

Do not weaken or delete warehouse graph identity, DB migration/settlement audits, backup/recovery verification, or product/picking UAT semantics. Integrate them as project-specific collectors/contracts after parity is proven.

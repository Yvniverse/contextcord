# Portable task state

`memory export` transfers one Task, its Sessions, Notes, dependency fingerprints,
Context Jobs, historical evidence and source event proofs. The archive contains
canonical JSON objects and SHA-256-addressed non-source evidence payloads.

```bash
contextcord memory export --task-id task-123 --out task-state.zip
contextcord memory import --bundle task-state.zip --dry-run
contextcord memory import --bundle task-state.zip
contextcord memory show --task-id task-123
contextcord memory handoff --task-id task-123 --scope code
```

Run import commands in the destination project. `memory handoff` starts a local
session from imported state; `handoff --assist` additionally previews and archives
a bounded selected packet. The MCP read path uses `contextcord_memory` and
`contextcord_memory_recheck`.

Manifest, object, payload and source-event hashes are verified before mutation.
One bundle contains one task; conflicting event identities and cross-task objects
are rejected. Safe paths reject traversal, drive syntax, symlinks and credential
file names. Identical imports return `NOOP` and preserve the current local state.

Dependency drift appears as `STALE` or `MISSING` and requires revalidation.
Imported evidence keeps its historical status and `NOT_EVALUATED` qualification
until the destination project performs its own checks. Credentials, source files
and absolute repository paths are excluded from the transfer contract.

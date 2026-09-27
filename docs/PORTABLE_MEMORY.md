# ContextCord portable live memory

ContextCord is a pluggable Open Core / CLI / MCP / Coding Agent Adapter
infrastructure. The repository-local CLI and MCP server are the product
runtime. The web page is an optional onboarding, demo and inspection surface;
it is not required to use or migrate memory.

## What moves

`contextcord memory export` transfers one live Task, its Sessions, Notes, dependency
fingerprints, archived Context Jobs, historical evidence, source event proofs
and non-source evidence payloads. The archive is a versioned ZIP containing
canonical JSON objects and SHA-256-addressed payloads.

The bundle deliberately does not transfer `.env`, private keys, absolute
repository paths or current qualification. Imported evidence is marked
`HISTORICAL`; its old `PASS` or `FAIL` status is retained as history only.
Current qualification remains `NOT_EVALUATED` until the target repository
performs its own checks.

## Export, import, resume

```powershell
# Source repository A
contextcord --repo D:\work\repo-a memory export --task-id task-123 --out D:\transfer\task-123.zip

# Fresh repository path B: inspect without mutation
contextcord --repo D:\work\repo-b memory import --bundle D:\transfer\task-123.zip --dry-run

# Transactional import
contextcord --repo D:\work\repo-b memory import --bundle D:\transfer\task-123.zip
contextcord --repo D:\work\repo-b memory show --task-id task-123

# Start a new local Session and continue
contextcord --repo D:\work\repo-b memory resume --task-id task-123 --scope code
contextcord --repo D:\work\repo-b memory note add --task-id task-123 --text "Continue from imported task"
```

The same read path is available through the local MCP server:

```powershell
contextcord --repo D:\work\repo-b mcp
```

Call `contextcord_memory` to inspect the Task/Session/Note graph and
`contextcord_memory_recheck` to recompute relative dependency status. The default
MCP surface is read-only. `contextcord_memory` does not execute a shell and does
not turn historical evidence into a completion decision.

## Integrity and isolation rules

- Manifest, object and payload hashes are checked before import.
- One bundle contains one Task; cross-task records and event-chain conflicts
  are rejected.
- Relative paths reject absolute paths, parent traversal, Windows drive
  syntax, symlinks and secret-like names.
- Import is transactional and idempotent. A byte-identical repeat is `NOOP`;
  a conflicting repeat is `CONFLICT` and leaves local state unchanged.
- Dependency changes are visible as `STALE` or `MISSING` with
  `REVALIDATE`; they never silently become current PASS.

## Acceptance evidence

Historical acceptance fixtures and bundle manifests remain in private release
evidence and are not part of the public staging surface. Session IDs are
generated per run; use the JSON evidence produced by the current repository
rather than copying example IDs into another task.

The fixture relocates to fresh Git paths on the same Windows host. It does not
claim a physical second-device test. A real cross-device transfer still uses
the same archive contract, but its host and OS evidence must be recorded
separately.

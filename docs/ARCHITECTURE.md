# Architecture

ContextCord uses one repository-local StateStore with a shared capability registry.

| Product module | Implementation |
| --- | --- |
| Continuum | `workflow.py`, `context.py`, `store.py`, `handoff.py`, `closeout.py` |
| Context Engine | `memory.py`, `bm25.py`, `continuity.py` and packet assembly in `handoff.py` |
| Veritas | `identity.py`, `fingerprint.py`, `evidence.py`, `receipt.py`, `portable.py`, `qualification.py` |
| Decision Plane | `decision_fabric.py`, `decision.py`, `policy.py`, `router.py`, `model_intelligence.py` |
| MCP / Host Gateway | `mcp.py`, `service.py`, `hostbridge.py`, `adapters.py`, `host_configs.py`, `host_registry.py` |
| Jev (optional) | `jev_provider.py`, loaded only when the provider is requested |

The mapping is a product view over shared code; modules compose through the
same store, identity and policy contracts. See [runtime inventory](runtime_surface.json).

## Handoff path

```text
Task + Notes + Context Jobs + Evidence
              ↓
       deterministic BM25 ranking
              ↓
   dependency freshness and authority checks
              ↓
      at most 24 eligible candidates
              ↓
 local selection / optional Jev on ambiguity
              ↓
    up to 3 records + source identity
              ↓
 packet + decision receipt + archive references
```

Dependency hashes are checked against current files during candidate collection.
BM25 ranks relevance; stale or unresolved dependency records are excluded from
selection. Current authoritative candidates take precedence over historical
material. A packet can refer to archived context jobs without treating them as
current evidence. A provider outage or invalid selection records a deterministic
BM25 fallback. A failed event chain blocks Handoff.

Preview adds no sessions, context jobs or events. Confirmation checks the event
chain and unfinished task again; an immediate SQLite transaction covers the
open-session check, session creation, context job and audit event. Concurrent
confirmations create at most one new open session for a task.

## Decision and execution boundaries

Gate 0 decides whether semantic advice is useful. The gate bundle has ten typed
decision categories. A deep selection stage can request relevance scores.
Deterministic policy owns permissions, integrity enforcement, tests, destructive
approval and release gates. Semantic ranking must return unique IDs from the
eligible pool and cannot select through a hard gate.

MCP derives tool exposure from the effective capability set and its mutation
flag. Host adapters translate host contracts into this application boundary.
Host permissions and OS isolation remain authoritative for execution.

## Identity and portable state

Veritas binds records to Git, content and policy identity. Dependency changes
mark associated notes for revalidation. Portable bundles verify object hashes,
safe relative paths, inventory and source event chains before importing.
Imported evidence retains historical classification until separately qualified.

The optional source-bound observation API in `continuity.py` additionally checks
explicit file-hash snapshots and packs only current dependency-bound records.
It is distinct from the task-note Handoff facade above.

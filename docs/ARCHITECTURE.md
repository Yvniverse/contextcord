# Architecture

ContextCord has six vendor-neutral layers:

1. Continuity Core records tasks, sessions, notes and handoffs;
2. Context Engine selects bounded memory and restores evidence;
3. Trust & Freshness preserves source identity and stale/revalidation state;
4. Decision Fabric keeps typed Jev judgment behind deterministic gates;
5. MCP / Host Gateway translates native host contracts;
6. Evidence & Runtime records observations, permissions and receipts.

The selector never proves freshness or authorization. The Decision Fabric may
ask Jev a typed question, but code owns hard gates and side effects. A runner or
CLI assembles the final packet and records its hash before host execution.

See [Architecture Atlas](architecture/README.md) and [research boundaries](RESEARCH_BOUNDARIES.md) for the reviewed system boundary.

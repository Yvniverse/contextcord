# Host integration

ContextCord ships adapter/config contracts for Codex, Cursor, Qoder, OpenCode
and WorkBuddy. Host qualification is tracked separately from integration support.
Use the generated [runtime inventory](runtime_surface.json) for the exact tool surface.

```bash
contextcord adapter config --host codex
contextcord adapter config --host cursor
contextcord adapter config --host qoder
contextcord adapter config --host opencode
contextcord adapter config --host workbuddy
```

The commands print copyable host configuration; they do not modify host files.
Configure the MCP working repository with the host's working-directory setting,
or add `--repo <project>` before the `mcp` argument. Review host-specific setup
instructions printed with the configuration.

```bash
contextcord mcp
# Enable lifecycle mutations only when your host needs them:
contextcord mcp --allow-mutations
```

The full runtime declares 16 tools. Default MCP sessions expose read-only tools;
mutation flags and effective capabilities determine the active subset. Context,
memory, Handoff preview and verification use the same application boundary as CLI.
Handoff confirmation, start, checkpoint, advance and finish require mutations.

| Profile | Capabilities |
| --- | --- |
| minimal | core, evidence |
| continuity | core, evidence, continuity, memory, handoff, MCP, hosts, closeout |
| decision | core, evidence, decision, router, model intelligence |
| full | all 12 runtime capabilities |

Profiles include their dependencies. Jev is installed/configured separately:

```bash
python -m pip install -e ".[jev]"
contextcord feature enable jev
contextcord provider jev status
contextcord handoff --assist --task-id <id> --provider jev_api
```

Configure `TYPESAFE_API_KEY` in your local environment or project `.env`.
Provider status reports availability without exposing credential values.
An unavailable provider records deterministic fallback during Handoff.

Adapters translate host events and configuration. Scope permissions, evidence
checks and lifecycle rules remain in ContextCord's core. The host and OS govern
actual tool execution. Use `contextcord adapter capabilities --host <host>` and
`contextcord adapter check --host <host> --scope <scope>` to inspect differences.

[BYOH adapter manifests](ADAPTERS.md) · [Typed decisions](JEV_DECISION_FABRIC.md).

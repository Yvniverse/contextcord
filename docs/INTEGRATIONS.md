# Host integrations

ContextCord ships five first-class built-in hosts. They share the same product
tier; each host's native configuration contract stays in its adapter while the
core policy and evidence model remains host-neutral.

| Host | Project configuration | Verification |
| --- | --- | --- |
| Codex | `~/.codex/config.toml` or `.codex/config.toml` | `codex mcp list` |
| Qoder | `.mcp.json` or Qoder settings | `qoder mcp list` or `/mcp reload` |
| Cursor | `.cursor/mcp.json` or global MCP settings | Cursor MCP panel or `cursor-agent mcp list` |
| OpenCode | `opencode.json` / `opencode.jsonc` | `opencode mcp list` |
| WorkBuddy | `.mcp.json` or `~/.codebuddy/.mcp.json` | `codebuddy mcp list` |

Codex uses this TOML entry:

```toml
[mcp_servers.contextcord]
command = "contextcord"
args = ["mcp"]
```

The equivalent registration command is:

```text
codex mcp add contextcord -- contextcord mcp
codex mcp list
```

The primary ContextCord stdio server entry for JSON-shaped hosts is:

```json
{
  "mcpServers": {
    "contextcord": {
      "command": "contextcord",
      "args": ["mcp"]
    }
  }
}
```

OpenCode uses its native shape:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "contextcord": {
        "type": "local",
        "command": ["contextcord", "mcp"]
      }
    }
  }
}
```

Use the contextcord namespace for all current CLI and MCP integrations. See [Migration](MIGRATION.md).

See `support/adapters/` for manifests and
[Host Evidence Registry v3](../research/host_evidence_registry_v3.json)
for the separate integration, continuation and qualification dimensions.
Legacy v2 payloads are compatibility-only history and are not part of the
current public staging surface.

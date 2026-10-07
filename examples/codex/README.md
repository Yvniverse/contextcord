# Codex MCP configuration

Use the accompanying `config.toml` to register ContextCord as a local stdio MCP
server. Set the project working directory through the host, or insert
`--repo <project>` before `mcp` in `args`.

Default configuration exposes read-only tools. To allow lifecycle mutations,
explicitly add `--allow-mutations` after `mcp` and review the project's scope policy.

The configuration contract is independent of live host qualification.
See [host integration](../../docs/INTEGRATIONS.md).

# ContextCord host adapters

Adapters translate host contracts into the vendor-neutral CLI/MCP boundary.
They do not duplicate policy decisions; host permissions and OS isolation remain
authoritative. A snippet produced by `contextcord adapter config` is a template
until a real host calls the local server and the result is recorded in the
[integration contract](INTEGRATIONS.md).

## Generate copyable configuration

```powershell
contextcord adapter config --host codex --repo-path D:\work\repo
contextcord adapter config --host claude --repo-path D:\work\repo
contextcord adapter config --host cursor --repo-path D:\work\repo
contextcord adapter config --host opencode --repo-path D:\work\repo
contextcord adapter config --host qoder --repo-path D:\work\repo
contextcord adapter config --host generic --repo-path D:\work\repo
```

The real stdio entry point is `contextcord mcp`. The historical
`project-harness` / `poh` commands remain compatibility aliases; use the
canonical command rather than inventing a second executable. Use an absolute
`--repo` when the host does not set repository cwd.

## Support boundary

| Host | Current status | What is actually claimed |
| --- | --- | --- |
| `contextcord` CLI + MCP stdio | `PASS` | `list_tools`, canonical memory tools, import and CLI resume were exercised on a fresh path |
| Codex 0.147.0 | `NOT_RUN` | Installed; temporary read-only attempt was blocked by local model transport; no global config changed |
| Cursor 2.5.26 | `CONFIG_TEMPLATE_ONLY` | Executable detected; MCP JSON generated, no host tool call observed |
| Qoder 1.24.2 | `CONFIG_TEMPLATE_ONLY` | Executable detected; command generated, no host tool call observed |
| OpenCode | `CONFIG_TEMPLATE_ONLY` | Not installed; V2 template generated, version schema still needs host verification |
| Claude Code | `CONFIG_TEMPLATE_ONLY` | Not installed; command template generated |

No row claims native automatic context capture or automatic compaction. Hooks,
where present, are lifecycle/policy adapters and are not a substitute for the
portable live-memory contract.

## MCP boundary

`contextcord --repo <absolute-repo> mcp` is local stdio JSON-RPC. The default
server is read-only and exposes memory inspection, identity, verification,
authorization evaluation and replay. Mutation workflow tools require the
explicit `--allow-mutations` switch and still call the Core gates. There is no
network transport, OAuth or multi-tenant session authority in this server.

For setup details see [Quick Start CN](QUICKSTART_CN.md),
[Quick Start EN](QUICKSTART_EN.md), and the [portable memory contract](PORTABLE_MEMORY.md).

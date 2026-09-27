# Codex + ContextCord

Register the ContextCord MCP server with Codex using either the config snippet in `config.toml` or the CLI:

```bash
codex mcp add contextcord -- contextcord mcp
codex mcp list
```

Then open Codex in the same project and ask it to inspect the active ContextCord task/session through the available `contextcord_*` MCP tools.

This example configures the integration only. Model-selection policy for live qualification experiments belongs to the experiment receipt/policy, not this reusable MCP config.

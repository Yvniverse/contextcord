# ContextCord quick start (CLI/MCP first)

ContextCord is pluggable Open Core / CLI / MCP / Coding Agent Adapter
infrastructure. Live engineering memory is repository-local and portable;
the website is optional onboarding, demonstration and inspection.

```powershell
python -m pip install -e ".[dev]"
cd D:\work\your-repo
contextcord init --profile generic
contextcord doctor
contextcord start --task-id issue-123 --scope code --json
contextcord memory note add --task-id issue-123 --text "Keep retry bounded"
contextcord --repo D:\work\your-repo memory export --task-id issue-123 --out D:\transfer\issue-123.zip
```

Restore in a fresh path:

```powershell
contextcord --repo D:\work\fresh-repo memory import --bundle D:\transfer\issue-123.zip --dry-run
contextcord --repo D:\work\fresh-repo memory import --bundle D:\transfer\issue-123.zip
contextcord --repo D:\work\fresh-repo memory show --task-id issue-123
contextcord --repo D:\work\fresh-repo memory resume --task-id issue-123 --scope code
contextcord --repo D:\work\fresh-repo mcp
```

Generate copyable host snippets with `contextcord adapter config --host <host> --repo-path
<repo>`. Generated snippets remain `CONFIG_TEMPLATE_ONLY` until the real host
observes `contextcord_memory` returning the Task and Notes. The verified route in
this workspace is the `contextcord` CLI plus local MCP stdio; see the
[integration contract](INTEGRATIONS.md).

The Jev backend reads `TYPESAFE_API_KEY` from the project `.env` only at request
time. The key is never put in host config, bundles, logs or evidence. Native
automatic agent compaction or capture is not claimed.

# Host adapters

Adapters translate host configuration and tool events into the same CLI/MCP
application boundary. Core code owns state transitions, permissions and evidence.

Generate built-in configuration with `contextcord adapter config --host <host>`.
Add `--repo-path <project>` when the host does not set the project working directory.
The default server is read-only; lifecycle mutations require `--allow-mutations`.
See [host integration](INTEGRATIONS.md).

## Bring your own host

```bash
contextcord adapters list
contextcord adapters init my-host --out my-host.adapter.json
contextcord adapters validate my-host.adapter.json
contextcord adapters render my-host.adapter.json --out host-config.json
```

Manifests describe transport, reload behavior, tool discovery, permissions and
observable telemetry. Built-in manifests and their schema are included in the
Python package. Validation rejects credential fields and unexpected contracts.

`adapters probe` and `adapters certify` run without host execution by default.
The certification ladder records template, configuration, MCP connection,
tool discovery, memory call, continuation and qualification separately.
Use `--execute` only after reviewing the host manifest and its commands.

Project-specific host evidence can be stored at `.contextcord/host-evidence.json`.
A fresh project starts with shipped contracts and no inherited qualification.

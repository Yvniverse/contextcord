# ContextCord quickstart

## Install

```powershell
python -m pip install -e ".[dev]"
contextcord init --profile generic
contextcord doctor
```

Create or resume a task with `contextcord resume --assist`. The CLI keeps
local task state and produces a bounded continuation context for the next host.

## Connect a host

Use the [integration guide](INTEGRATIONS.md) for Codex, Qoder, Cursor, OpenCode
and WorkBuddy. Other MCP hosts use a BYOH Adapter Manifest. The adapter translates
native syntax; it does not decide policy, permissions or evidence validity.

## Verify a continuation

Inspect source identity, freshness and evidence before opening a new session.
Only the final packet selected for the task should cross the host boundary.
Run the repository test command before calling a change complete:

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```

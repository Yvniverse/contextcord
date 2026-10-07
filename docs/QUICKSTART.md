# Quick start

Install the source checkout with Python 3.11+:

```bash
python -m pip install -e .
```

The following commands run in your own Git project, with an existing commit and
an `AGENTS.md` policy file. `init` writes editable `.contextcord` TOML files;
review the scope permissions and evidence requirements before using them.

```bash
contextcord init --profile generic
contextcord doctor
contextcord feature profile continuity
contextcord start --task-id retry-policy --scope code --json
contextcord memory note add --task-id retry-policy --text "Retry budget is bounded; add timeout tests." --depends-on src/client.py
contextcord handoff --assist --task-id retry-policy
```

Use a dependency path that exists in your project. The note records its current
content hash; a later change makes the note stale. The Handoff preview shows
selected memory, the source identity and records requiring revalidation.

Save the `session_id` returned by `start`. Before switching sessions:

```bash
contextcord finish --session-id <session_id> --mode handoff --summary-text "Continue timeout tests."
contextcord handoff --assist --task-id retry-policy --yes
```

Handoff confirmation creates one session and one archived context job. Concurrent
confirmation or an existing open session returns `OPEN_SESSION_EXISTS`.
`finish --mode complete` separately requires the configured workflow and evidence
gates. `verify --profile handoff` checks handoff state; `verify --ci` checks completion.

For portable task state:

```bash
contextcord memory export --task-id retry-policy --out task-state.zip
contextcord memory import --bundle task-state.zip --dry-run
contextcord memory import --bundle task-state.zip
contextcord memory show --task-id retry-policy
```

Run imports in the destination project. Objects and source event chains are
verified before mutation; imported evidence retains historical classification.
Repeated identical imports are idempotent.

[Host configuration](INTEGRATIONS.md) · [Architecture](ARCHITECTURE.md).

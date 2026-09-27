<h1 align="center">ContextCord</h1>

<p align="center"><strong>Engineering continuity for coding agents.</strong><br>
Keep project state, evidence and decisions bound to the repository—then carry only the context the next agent actually needs.</p>

<p align="center">
  <a href="README_CN.md">中文</a> ·
  <a href="web/docs/index.html">Docs</a> ·
  <a href="docs/ARCHITECTURE.md">Architecture</a> ·
  <a href="docs/INTEGRATIONS.md">Hosts</a> ·
  <a href="docs/ROUTER.md">Adaptive Router</a>
</p>

<p align="center">
  <img alt="Status: Public Alpha" src="https://img.shields.io/badge/status-public%20alpha-2f6f57">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-2f6f57">
  <img alt="Interface: MCP" src="https://img.shields.io/badge/interface-MCP-59675F">
</p>

ContextCord is a local-first continuity and decision layer for coding agents. It is not a chat-memory product: the repository remains the source of truth, old conclusions can be revalidated against current source, and the next session receives a bounded context packet instead of a transcript dump.

## Quick start

```bash
git clone https://github.com/Yvniverse/contextcord.git
cd contextcord
python -m pip install -e .

contextcord init --profile generic
contextcord doctor
contextcord resume --assist
```

`resume --assist` starts with a read-only continuation preview. A new source-bound session is created only after confirmation.

## Six modules, one local truth layer

| Module | Problem it solves | What it owns | One-line value |
| --- | --- | --- | --- |
| **Continuum** | How does engineering work survive a new session or host? | Task, Session, Checkpoint, Handoff, Closeout, Resume | **Remember engineering progress, not chat history.** |
| **Context Engine** | What should the next agent actually see? | Bounded selection, BM25, freshness/authority signals, recheck, recoverable references | **Select the context that matters instead of replaying everything.** |
| **Veritas** | Why should an old conclusion still be trusted? | Source identity, fingerprints, Evidence, Receipt chains, Qualification, replay | **Keep why a conclusion was valid—not only the conclusion.** |
| **Decision Plane** | How are ambiguous choices and model routes decided? | Deterministic policy, Adaptive Router v3, Model Intelligence, receipts, Local Outcome | **Models may advise; code keeps authority.** |
| **MCP / Host Gateway** | How can the same project continue across coding agents? | Dynamic MCP tool surface, Host Registry/configuration, BYOH adapters | **One project state layer across multiple coding agents.** |
| **Jev** · optional | Which narrow decisions benefit from semantic judgment? | Optional typed provider on bounded decision paths | **Use an LLM as a bounded semantic advisor, not an unrestricted executor.** |

These are product modules, not six packages or databases. Internally, ContextCord uses one Capability Registry and one repository-local StateStore.

## Use only what you need

```bash
contextcord feature profile minimal
contextcord feature profile continuity
contextcord feature profile decision
contextcord feature profile full
```

- `minimal` — core + evidence
- `continuity` — continuity, memory, handoff, MCP/hosts and closeout
- `decision` — deterministic decision, Adaptive Router and Model Intelligence
- `full` — all runtime capabilities, including Jev when installed/configured
- `custom` — explicit enable/disable combinations

Jev is intentionally separate from the default `decision` profile:

```bash
python -m pip install -e ".[jev]"
contextcord feature enable jev
contextcord provider jev status
```

Provider credentials stay local and are not written into public receipts.

## How the pieces work together

```text
Continuum ──→ Context Engine ──→ bounded continuation
   │               │
   └──────→ Veritas ───────────→ source-aware evidence
                   │
                   └────→ Decision Plane ──→ effective route
                                  │
                            optional Jev
                                  │
                                  ↓
                         MCP / Host Gateway
                                  │
                                  ↓
                         real host execution
                                  │
                                  ↓
                         verifier + local outcome
```

The modules are a responsibility view, not a rigid one-file/one-module partition. Shared capabilities may contribute to more than one product module without creating a second registry.

## Host integrations

Built-in integration contracts are provided for **Codex, Cursor, Qoder, OpenCode and WorkBuddy**, with a versioned BYOH adapter path for other hosts. “Built-in” describes the shipped integration contract; live model qualification is recorded separately in the current Host Evidence Registry.

## Adaptive Router

The Decision Plane can choose an eligible `model × reasoning-effort × role` route. Hard code-owned rules define what can execute; external Model Intelligence is advisory; Jev is called only when a bounded semantic choice is useful. Only real host execution plus verifier output can become Local Outcome evidence.

See [Adaptive Router](docs/ROUTER.md) and [Research boundaries](docs/RESEARCH_BOUNDARIES.md).

## Architecture

The [Architecture Atlas](docs/ARCHITECTURE.md) includes six complementary interactive Archify views: system architecture, Adaptive Router, workflow, sequence, data flow and lifecycle. The site shows six categories for the active language while retaining both Chinese and English standalone viewers.

## Security and local data

ContextCord is local-first. Project state, provider credentials, raw Model Intelligence payloads and private delivery evidence are not part of the public repository surface. Host permissions and the operating system remain authoritative for real execution.

See [SECURITY.md](SECURITY.md).

## Project status

ContextCord is **Public Alpha**. Continuity, evidence, capability and MCP contracts are the primary product surface. Adaptive routing, external Model Intelligence and outcome calibration remain experimental behind explicit capability boundaries.

## Contributing

Issues, documentation, reproducible benchmark methodology and carefully scoped host integrations are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## License & acknowledgements

ContextCord 0.6.2a1 Public Alpha is distributed under the [MIT License](LICENSE). Third-party and generated assets remain subject to their own notices and licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md). Architecture documentation uses [Archify](https://github.com/tt-a1i/archify); optional Model Intelligence may consume attributed public observations from [CodexRadar / DRadar](https://deng.codexradar.com/) as an advisory data source.

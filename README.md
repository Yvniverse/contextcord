# ContextCord

**Engineering continuity and trustworthy context for Coding Agents.**

[中文](README_CN.md) · [Website](https://contextcord.pages.dev) · [Quick start](docs/QUICKSTART.md) · [Architecture](docs/ARCHITECTURE.md) · [Host integration](docs/INTEGRATIONS.md)

ContextCord is a local-first continuity and trustworthy-context layer for Coding
Agents. It persists engineering state outside individual chats, binds recovered
context to repository and source identity, revalidates state when dependencies
change, and exposes capability-scoped tools to agent hosts.

| 5,040 | −84.9% | 299 / 300 |
| --- | --- | --- |
| Engineering records recovered across 60 continuity replays | Bounded Handoff payload vs a 24 KB text baseline | Typed judgments matched the frozen rubric |

## Get started

Install from a source checkout with Python 3.11+:

```bash
python -m pip install -e .
```

Run in your Git project, with at least one commit and an `AGENTS.md` policy file:

```bash
contextcord init --profile generic
contextcord doctor
contextcord feature profile continuity
contextcord handoff --assist
```

Handoff starts with a read-only preview. After closing the preceding session,
confirm with `contextcord handoff --assist --task-id <id> --yes` to create one
local session and archive its context packet. See the [task walkthrough](docs/QUICKSTART.md).

## Six modules

| Module | Responsibility |
| --- | --- |
| **Continuum** | Task, Session, Checkpoint, Handoff and Closeout lifecycle |
| **Context Engine** | BM25 candidate reduction, freshness, authority and bounded packets |
| **Veritas** | Source identity, dependency fingerprints, object and receipt integrity |
| **Decision Plane** | Deterministic policy, typed decisions and optional route planning |
| **MCP / Host Gateway** | Capability-scoped tools and host adapter/config contracts |
| **Jev** (optional) | Narrow semantic judgments and selection on ambiguous candidate pools |

One repository-local StateStore connects the modules. The code-derived surface
has **12 runtime capabilities**, **16 MCP tools** and **10 typed decision categories**.
[Generated inventory](docs/runtime_surface.json).

Handoff collects local candidates, ranks them with BM25, checks source freshness
and authority, and reduces the eligible pool to at most 24 candidates. The default
path selects up to three records locally. When explicitly enabled, Jev can rank
an ambiguous pool; unavailable or invalid advice uses a recorded BM25 fallback.
The resulting packet links source identity, archive references and its decision
receipt. Stale records remain marked for revalidation.

Deterministic code owns permissions, integrity, execution controls, tests,
destructive approval and release gates. Host permissions and OS isolation govern
real execution. [Security model](SECURITY.md).

## Evaluation

| Measurement | Recorded result |
| --- | --- |
| Task-spec-derived continuity replays | 60 |
| Task fields and lossless note sets recovered | 60/60 each; 5,040 notes |
| Handoff payload vs bounded-text baseline | 217,067 B / 1,440,000 B; 84.9% reduction |
| Dependency-bound records marked for revalidation after source changes | 180; stale selections 0 |
| Tampered objects rejected | 60/60 |
| Synthetic typed judgments matched the frozen rubric | 299/300; 99.7% |
| Live batched typed requests and latency | 30; P95 453 ms |
| Deterministic gate replay | Observed bypasses 0/300 |

The continuity replay measures exact state recovery and packet size across 60
task-spec-derived fixtures. The synthetic typed evaluation measures the typed
decision contract. All table values can be recomputed from the included rows:

```bash
python evaluation/continuity/recompute.py --check
python evaluation/typed_decisions/recompute.py --check --replay
```

[Evaluation method and artifacts](docs/EVALUATION.md).

## Host integration and profiles

Ships adapter/config contracts for **Codex, Cursor, Qoder, OpenCode and WorkBuddy**;
host qualification is tracked separately from integration support.

Use `contextcord feature profile minimal`, `continuity`, `decision` or `full` to
select a capability set. MCP mutations require the explicit `--allow-mutations`
server option. Jev is optional: install `.[jev]`, enable the capability and
configure credentials locally. [Profiles and host setup](docs/INTEGRATIONS.md).

Optional model routing and external Model Intelligence provide advisory route
planning. [Decision Plane](docs/ROUTER.md).

## Development and license

ContextCord 0.6.2a1 is an alpha release candidate. See [CONTRIBUTING.md](CONTRIBUTING.md)
for verification commands. Distributed under [Apache-2.0](LICENSE), with retained
[third-party notices](THIRD_PARTY_NOTICES.md) and [acknowledgements](ACKNOWLEDGEMENTS.md).

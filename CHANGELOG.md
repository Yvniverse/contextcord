# Changelog

## 0.6.2a1 — Adaptive Router Calibration

### Added

- Jev live semantic route choice remains closed to the Router shortlist, with usage and latency kept separate from planner and effective-route receipts.
- Bounded Codex execution-route discovery with CONFIRMED, CONFIGURED_EXPLICIT, UNKNOWN and UNAVAILABLE capability states.
- Adaptive Explorer / Implementer / Reviewer calibration budgets and identity-aware local outcome learning.
- `verify --profile handoff` and `verify --profile complete`; `verify --ci` remains strict COMPLETE verification.
- Permanent private Git completion contract in `AGENTS.md`.

### Boundaries

- CodexRadar remains an external prior; raw payloads and private local outcomes stay out of release artifacts.
- Public publication remains NOT_DONE.

## 0.6.2a0 — Modular Capabilities & Live Model Intelligence

### Added
- A single capability registry with profiles, dependency closure and structured feature status.
- Atomic `feature` configuration, secret-safe Jev provider status/doctor commands and dynamic MCP tool exposure.
- Explicit CodexRadar opt-in snapshot/refresh commands with derived-only receipts and bounded cache fallback.
- StateStore-backed local model-route outcomes and Router summary/show commands.

### Changed
- The CodexRadar provider no longer requires the private-dogfood flag; capability/provider configuration is authoritative.
- Jev remains optional and manual by default; API keys are never written to ContextCord state or release artifacts.

## 0.6.1a2 — Public Alpha Candidate

### Added
- Canonical reconciliation against private `Yvniverse/contextcord` `origin/main`.
- Jev Router v2 route identity with explicit GPT-5.6 model and reasoning effort.
- Quality-constrained, cost-aware shortlist selection with a hard two-attempt execution boundary.
- Optional read-only CodexRadar model-intelligence prior with fresh/stale/unavailable cache states.
- Calibration receipt and hard budget caps: six live calls per round and one Sol Max run.

### Changed
- Release identity, host-tier evidence and package metadata now target `0.6.1a2`.
- Codex model eligibility is closed to explicit `gpt-5.6-luna`, `gpt-5.6-terra` and `gpt-5.6-sol` identities; aliases and fallback routes are rejected.

## 0.6.1a1 — Unreleased

### Added
- OpenAI Codex as a fifth first-class built-in host with native ContextCord MCP configuration.
- ContextCord-native Host Evidence Registry v3 with read compatibility for the v2 Agent-Nexus registry.
- Codex integration receipts with an explicit GPT-5.6 Luna Max-only host-experiment policy.
- GitHub issue forms and pull-request template for bugs, features and host integrations.
- Public Surface Brand Gate v2.

### Changed
- Reworked README/README_CN around quick adoption, host integrations, architecture and research links.
- Reworked Code of Conduct, Contributing and Security entry points for a public open-source repository.
- Clarified NOTICE/provenance presentation for the ContextCord product line.

### Research
- Optional Jev Router × Codex bounded pilot across runtime-resolved GPT-5.6-family models. Record actual results only after execution.

## 0.6.0-alpha.1

- Reframe the product as ContextCord, with bilingual public Homepage, Docs,
  Integrations, Research and README surfaces.
- Add vendor-neutral Host Evidence Registry v2 for Qoder, Cursor, OpenCode and
  WorkBuddy, plus BYOH adapter guidance.
- Add a real BM25 selector and a production Decision Fabric selection boundary.
- Separate the deterministic Context Sufficiency Test from Live Benchmark v3,
  whose runner keeps bounded context, candidate pools and hidden oracles apart.
- Stage a local-only public repository candidate; no external repository or
  hosted CI result is implied.

## 0.4.0rc1

- Converge user-supplied Unified and ProjectTrust reference designs into one core.
- Seal v3 receipts with core build and stable local store identity; reject silent state recreation.
- Make session, evidence and lease mutations transactional with their audit events.
- Serialize schema migration and retry concurrent initial WAL setup.
- Add explicit portable receipt/event/evidence verification and bounded archive validation.
- Bound subprocess output during capture, apply default execution timeout, and give each run unique evidence paths.
- Revalidate phase evidence; reject stale source identity at advancement.
- Use CAS publication for concurrent Git Notes qualification updates.
- Preserve Unicode Git paths and Windows Git executable modes.
- Add local stdio MCP, verified event timeline replay, Claude/Cursor adapter configurations, extension protocols and a reusable CI action.
- Add cross-platform tests, external snapshot integration and isolated wheel smoke tooling.

Compatibility: historical v2 receipts are readable but cannot satisfy new v3 store/build
requirements. Fresh CI must use `bundle verify`; artifact import is not state migration.
This candidate does not include production Team/Cloud services or live-host certification.

# ContextCord Architecture Atlas

This directory is the source-backed Architecture Truth baseline for
ContextCord 0.6.2a1. It contains six current views in two languages (12
standalone Archify maps), their typed specifications, delivery receipts, and
the generated inventory of `src/contextcord/*.py`.

The nine logical responsibility groups are labels over the current Python
modules, not independent deployment services. The active atlas intentionally
contains only `system`, `router`, `workflow`, `sequence`, `dataflow`, and
`lifecycle`; older proposal views remain historical evidence outside the
active selector.

The homepage keeps only lightweight diagram metadata and lazy-loads the
selected standalone viewer URL. The complete interactive Archify viewers
remain under `maps/`; no full viewer payload is embedded in the homepage.

## Status

- Source package: `src/contextcord/`
- Source inventory: `source-inventory.json`
- Active specs/maps: 12 / 12
- Fingerprint: `fingerprint.json` (v3)
- Public publication: `NOT_DONE`

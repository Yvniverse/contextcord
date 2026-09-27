# Host tier matrix

The release keeps product integration, native continuation evidence and live
qualification independent. A tier is not a qualification result.

| Tier | Hosts | Meaning in the current Public Alpha candidate |
| --- | --- | --- |
| `BUILT_IN` | Codex, Qoder, Cursor, OpenCode, WorkBuddy | First-class adapter/configuration surface. Each host still needs its own observable evidence. |
| `COMPAT_TEMPLATE` | Claude, DeepSeek | Copyable configuration templates only; no built-in qualification claim. |
| `BYOH` | Generic MCP, Adapter Manifest | User-owned host contract; the adapter translates syntax and does not duplicate policy. |

The canonical machine-readable sources are `support/host_tiers.json` and
`research/host_evidence_registry_v3.json`.

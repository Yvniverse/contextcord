# 宿主集成

ContextCord 提供五个一级 built-in 宿主。它们拥有相同的产品等级；每个宿主的
原生配置合同留在自己的 adapter 中，核心策略和证据模型保持宿主中立。

| 宿主 | 项目配置 | 验证 |
| --- | --- | --- |
| Codex | `~/.codex/config.toml` 或 `.codex/config.toml` | `codex mcp list` |
| Qoder | `.mcp.json` 或 Qoder settings | `qoder mcp list` 或 `/mcp reload` |
| Cursor | `.cursor/mcp.json` 或全局 MCP settings | Cursor MCP 面板或 `cursor-agent mcp list` |
| OpenCode | `opencode.json` / `opencode.jsonc` | `opencode mcp list` |
| WorkBuddy | `.mcp.json` 或 `~/.codebuddy/.mcp.json` | `codebuddy mcp list` |

Codex 使用下面的 TOML 配置：

```toml
[mcp_servers.contextcord]
command = "contextcord"
args = ["mcp"]
```

等价的注册命令是：

```text
codex mcp add contextcord -- contextcord mcp
codex mcp list
```

对于 JSON 形状的宿主，ContextCord 主 stdio server 配置如下：

```json
{
  "mcpServers": {
    "contextcord": {
      "command": "contextcord",
      "args": ["mcp"]
    }
  }
}
```

OpenCode 使用自己的配置形状：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "contextcord": {
        "type": "local",
        "command": ["contextcord", "mcp"]
      }
    }
  }
}
```

`contextcord`、`contextcord` 与 `contextcord_*` 仅保留为弃用的兼容别名。其它宿主必须
声明版本化的 BYOH Adapter Manifest 合同与 `product_tier: BYOH`。

Manifest 见 `support/adapters/`；[Host Evidence Registry v3](../research/host_evidence_registry_v3.json)
分别记录 integration、continuation 和 qualification 三个维度。旧 v2 payload
只作为兼容历史读取，不进入当前 public staging surface。

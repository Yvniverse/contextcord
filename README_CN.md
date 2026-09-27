<h1 align="center">ContextCord</h1>

<p align="center"><strong>让 Coding Agent 延续工程，而不是延续聊天记录。</strong><br>
把项目状态、依据与决策绑定到真实仓库，再只把下一位 Agent 真正需要的上下文带过去。</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="web/docs/index.html">Docs</a> ·
  <a href="docs/ARCHITECTURE_CN.md">架构</a> ·
  <a href="docs/INTEGRATIONS_CN.md">宿主</a> ·
  <a href="docs/ROUTER_CN.md">Adaptive Router</a>
</p>

<p align="center">
  <img alt="状态：Public Alpha" src="https://img.shields.io/badge/status-public%20alpha-2f6f57">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB">
  <img alt="MIT License" src="https://img.shields.io/badge/license-MIT-2f6f57">
  <img alt="MCP" src="https://img.shields.io/badge/interface-MCP-59675F">
</p>

ContextCord 是面向 Coding Agent 的本地优先工程连续性与决策层。它不是“聊天记忆”产品：真实仓库始终是工程真值，旧结论可以针对当前源码重新验证，下一次会话拿到的是有界 Context Packet，而不是整段历史对话。

## 60 秒开始

```bash
git clone https://github.com/Yvniverse/contextcord.git
cd contextcord
python -m pip install -e .

contextcord init --profile generic
contextcord doctor
contextcord resume --assist
```

`resume --assist` 先给出只读接续预览；确认后才建立新的 source-bound session。

## 六个模块，一套本地真值

| 模块 | 它解决的问题 | 当前职责 | 一句话价值 |
| --- | --- | --- | --- |
| **Continuum** | 如何跨会话、跨宿主继续同一项工程工作 | Task、Session、Checkpoint、Handoff、Closeout、Resume | **记住工程进度，而不是记住聊天记录** |
| **Context Engine** | 下一位 Agent 到底该看到什么 | 有界选择、BM25、freshness/authority、recheck、可恢复引用 | **选择最需要的上下文，而不是把历史全部塞回模型** |
| **Veritas** | 为什么旧结论现在还值得相信 | Source Identity、Fingerprint、Evidence、Receipt Chain、Qualification、Replay | **不仅保留结论，还保留结论为什么成立** |
| **Decision Plane** | 模糊选择和模型路线由谁决定 | Deterministic Policy、Adaptive Router v3、Model Intelligence、Receipt、Local Outcome | **模型可以判断，但代码保留最终边界** |
| **MCP / Host Gateway** | 怎么跨多个 Coding Agent 继续工作 | 动态 MCP Tool Surface、Host Registry/Config、BYOH Adapter | **一个核心状态层，接入多个 Coding Agent** |
| **Jev** · 可选 | 哪些窄问题值得语义判断 | 只在有界 Decision Path 上启用的 typed provider | **把 LLM 从执行者降级成有边界的语义顾问** |

六个模块是产品职责视图，不是六个独立 Python 包或六套数据库。内部继续由一份 Capability Registry 和一个 repository-local StateStore 控制运行时组合。

## 只启用你需要的能力

```bash
contextcord feature profile minimal
contextcord feature profile continuity
contextcord feature profile decision
contextcord feature profile full
```

- `minimal` — core + evidence
- `continuity` — continuity、memory、handoff、MCP/hosts、closeout
- `decision` — deterministic decision、Adaptive Router、Model Intelligence
- `full` — 全部 runtime capability；安装/配置后包含 Jev
- `custom` — 自定义 enable / disable

Jev 不再默认绑在 `decision` profile：

```bash
python -m pip install -e ".[jev]"
contextcord feature enable jev
contextcord provider jev status
```

Provider 凭据保留在本地，不写入公开 receipt。

## 六个模块如何协作

```text
Continuum ──→ Context Engine ──→ 有界接续上下文
   │               │
   └──────→ Veritas ───────────→ Source-aware Evidence
                   │
                   └────→ Decision Plane ──→ Effective Route
                                  │
                              可选 Jev
                                  │
                                  ↓
                         MCP / Host Gateway
                                  │
                                  ↓
                          真实宿主执行
                                  │
                                  ↓
                         Verifier + Local Outcome
```

模块是职责视图，不要求源码文件严格一对一归属。共享 capability 可以同时服务多个产品模块，而不创建第二套 Registry。

## 宿主集成

ContextCord 内置 **Codex、Cursor、Qoder、OpenCode、WorkBuddy** 的集成合同，并提供版本化 BYOH Adapter 路径。“Built-in”表示仓库自带集成合同，不等于当前模型已完成 live qualification；运行证据由当前 Host Evidence Registry 单独记录。

## Adaptive Router

Decision Plane 可以选择可执行的 `model × reasoning-effort × role` 路线。代码硬规则先决定哪些 route 有资格执行；外部 Model Intelligence 只提供 advisory prior；Jev 只在需要有界语义判断时介入。只有真实宿主执行并经过 verifier 的结果，才进入 Local Outcome。

详见 [Adaptive Router](docs/ROUTER_CN.md) 与 [研究边界](docs/RESEARCH_BOUNDARIES_CN.md)。

## 架构

[Architecture Atlas](docs/ARCHITECTURE_CN.md) 提供六类完整交互式 Archify 图：系统架构、Adaptive Router、Workflow、Sequence、Data Flow、Lifecycle。网页当前语言只显示六类，同时保留中英文两套 standalone viewer。

## 安全与本地数据

ContextCord 本地优先。项目状态、Provider 凭据、Model Intelligence raw payload 与私有交付证据都不属于公开仓库表面。真正的执行权限仍由宿主与操作系统控制。

安全问题见 [SECURITY.md](SECURITY.md)。

## 当前状态

ContextCord 处于 **Public Alpha**。Continuity、Evidence、Capability 与 MCP 合同是当前核心产品面；Adaptive Routing、External Model Intelligence 与 Outcome Calibration 仍属于显式能力边界后的实验功能。

## 参与贡献

欢迎 Issue、文档、可复现实验方法与边界清晰的宿主适配。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并遵守 [Code of Conduct](CODE_OF_CONDUCT.md)。

## 许可证与致谢

本仓库继续使用 [MIT License](LICENSE)。Apache-2.0 迁移在 Git history provenance 与 relicensing 权利独立核验前保持阻塞；本版本不宣称已经完成公开重许可。第三方归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。架构文档使用 [Archify](https://github.com/tt-a1i/archify)；可选 Model Intelligence 可以把 [CodexRadar / DRadar](https://deng.codexradar.com/) 的公开观测数据作为带归属的 advisory source。详见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md)。

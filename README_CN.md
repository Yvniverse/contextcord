# ContextCord

**Coding Agent 工程连续性与可信上下文基础设施。**

[English](README.md) · [网站](https://contextcord.pages.dev) · [快速开始](docs/QUICKSTART_CN.md) · [架构](docs/ARCHITECTURE_CN.md) · [Host 集成](docs/INTEGRATIONS_CN.md)

ContextCord 在本地保存跨会话的工程状态，将恢复的上下文绑定到仓库和源码身份，
在依赖变化后重新验证状态，并通过按能力授权的工具连接 Coding Agent host。

| 5,040 | −84.9% | 299 / 300 |
| --- | --- | --- |
| 60 个 continuity replay 中恢复的工程记录 | Handoff payload 相对 24 KB 文本基线的缩减 | 与 frozen rubric 一致的 typed judgments |

## 快速开始

使用 Python 3.11+，从源码安装：

```bash
python -m pip install -e .
```

在具有至少一个 commit 和 `AGENTS.md` 策略文件的 Git 项目中运行：

```bash
contextcord init --profile generic
contextcord doctor
contextcord feature profile continuity
contextcord handoff --assist
```

Handoff 首先生成只读预览。关闭上一 session 后，使用
`contextcord handoff --assist --task-id <id> --yes` 确认，创建一个本地 session
并归档其 context packet。完整流程见[任务示例](docs/QUICKSTART_CN.md)。

## 六个模块

| 模块 | 职责 |
| --- | --- |
| **Continuum** | Task、Session、Checkpoint、Handoff、Closeout 生命周期 |
| **Context Engine** | BM25 候选缩减、freshness、authority 和有界 packet |
| **Veritas** | 源码身份、依赖指纹、对象与 receipt 完整性 |
| **Decision Plane** | 确定性策略、typed decisions 和可选路由规划 |
| **MCP / Host Gateway** | 按能力开放工具、host adapter/config contracts |
| **Jev**（可选） | 对有歧义的候选池执行窄范围语义判断与选择 |

模块共享仓库本地 StateStore。代码派生的接口包含 **12 项运行时能力**、
**16 个 MCP 工具**和 **10 类 typed decision**。[生成的接口清单](docs/runtime_surface.json)。

Handoff 收集本地候选，经 BM25 排序、源码 freshness 与 authority 检查后，将可选池
缩减到最多 24 条。默认路径在本地选择最多三条记录。显式启用 Jev 后，可对有歧义的
候选池进行语义排序；服务不可用或建议无效时，使用有记录的 BM25 fallback。
最终 packet 关联源码身份、archive references 和 decision receipt；stale 记录保留
revalidation 标记。

确定性代码负责权限、完整性、执行控制、tests、破坏性操作审批和 release gates。
实际执行受 host 权限及 OS 隔离约束。[安全模型](SECURITY.md)。

## Evaluation

| 测量 | 已记录结果 |
| --- | --- |
| Task-spec-derived continuity replays | 60 |
| Task fields 与无损 note sets 恢复 | 各 60/60；5,040 条 notes |
| Handoff payload / bounded-text baseline | 217,067 B / 1,440,000 B；缩减 84.9% |
| 源码变化后进入 revalidation 的依赖记录 | 180；stale selections 0 |
| Tampered objects rejected | 60/60 |
| 与 frozen rubric 一致的 synthetic typed judgments | 299/300；99.7% |
| Live batched typed requests 与延迟 | 30；P95 453 ms |
| Deterministic gate replay | Observed bypasses 0/300 |

Continuity replay 在 60 个 task-spec-derived fixtures 上测量精确状态恢复与 packet
大小。Synthetic typed evaluation 测量 typed decision contract。以上数字均可从公开 rows 重算：

```bash
python evaluation/continuity/recompute.py --check
python evaluation/typed_decisions/recompute.py --check --replay
```

[方法与 artifacts](docs/EVALUATION_CN.md)。

## Host 集成与配置

提供 **Codex、Cursor、Qoder、OpenCode、WorkBuddy** 的 adapter/config contracts；
host qualification 与集成支持分别记录。

通过 `contextcord feature profile minimal`、`continuity`、`decision`、`full` 选择能力。
MCP 写操作需要显式使用 `--allow-mutations`。Jev 为可选组件：安装 `.[jev]`、启用能力，
在本地配置凭证。[Host 与 profile 配置](docs/INTEGRATIONS_CN.md)。

可选模型路由和外部 Model Intelligence 提供建议性的路由规划。[Decision Plane](docs/ROUTER_CN.md)。

## 开发与许可

ContextCord 0.6.2a1 为 alpha release candidate。[CONTRIBUTING.md](CONTRIBUTING.md)
列出验证命令。使用 [Apache-2.0](LICENSE)，并保留[第三方声明](THIRD_PARTY_NOTICES.md)
和[致谢](ACKNOWLEDGEMENTS.md)。

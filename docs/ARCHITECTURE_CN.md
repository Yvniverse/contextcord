# 架构

ContextCord 使用一个仓库本地 StateStore 和共享 Capability Registry。

| 模块 | 实现 |
| --- | --- |
| Continuum | `workflow.py`、`context.py`、`store.py`、`handoff.py`、`closeout.py` |
| Context Engine | `memory.py`、`bm25.py`、`continuity.py` 和 Handoff packet assembly |
| Veritas | `identity.py`、`fingerprint.py`、`evidence.py`、`receipt.py`、`portable.py`、`qualification.py` |
| Decision Plane | `decision_fabric.py`、`decision.py`、`policy.py`、`router.py`、`model_intelligence.py` |
| MCP / Host Gateway | `mcp.py`、`service.py`、`hostbridge.py`、`adapters.py`、`host_configs.py`、`host_registry.py` |
| Jev（可选） | `jev_provider.py`，仅在请求对应 provider 时加载 |

模块通过同一个 store、identity 与 policy contract 协作。[运行时清单](runtime_surface.json)。

Handoff 的实际路径：收集 Task/Notes/Context Jobs/Evidence → BM25 排序 → dependency
freshness 和 authority 检查 → 最多 24 条可选候选 → 本地选择或可选 Jev 语义选择 →
最多三条记录的 packet，并关联源码身份、decision receipt 与 archive references。

收集候选时，以当前文件内容检查依赖 hash。stale 或依赖无法验证的记录不能进入选择。
当前 authoritative 候选优先；historical context 可以作为归档引用，但不会升级为当前证据。
Provider 不可用或选择无效时记录 BM25 fallback；event chain 无效则阻止 Handoff。

预览不新增 session、context job 或 event。确认时再次检查 event chain 和未完成 task；
SQLite immediate transaction 包含 open-session 检查、session 创建、context job 与审计 event，
并发确认最多创建一个新的 open session。

Decision Plane 的 Gate 0 判断是否需要语义建议，初始 bundle 包含十类 typed decisions。
深层选择可请求 relevance scores。确定性代码拥有权限、完整性、tests、破坏性操作审批与
release gates；语义选择只能返回可选池中的唯一 ID。MCP 根据实际 capability 和 mutation flag
开放工具；host adapter 只翻译 host contract。实际执行受 host 权限和 OS 隔离约束。

Veritas 将记录绑定到 Git、内容和 policy 身份。Portable bundle 在导入前验证对象 hash、
相对路径、inventory 与 source event chain；导入证据保持 historical 分类，需单独 qualification。

`continuity.py` 另提供 source-bound observation API，检查显式文件 hash snapshot，并只打包
当前 dependency-bound 记录；它与上述 task-note Handoff facade 分别对应不同输入契约。

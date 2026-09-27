# 架构

ContextCord 包含六个厂商中立层：

1. Continuity Core：Task、Session、Note 与 Handoff；
2. Context Engine：有界记忆选择与证据恢复；
3. Trust & Freshness：源码身份、STALE 与重验证；
4. Decision Fabric：确定性 gate 之后的 typed Jev 判断；
5. MCP / Host Gateway：翻译宿主合同；
6. Evidence & Runtime：记录观察、权限与 receipt。

Selector 不证明新鲜度或授权。Decision Fabric 可以向 Jev 提出 typed question，
但硬 gate 和副作用由代码掌控。CLI 或 runner 组装最终 packet，并在宿主执行前
记录其 hash。

审定的架构基线见[Architecture Atlas](architecture/README.md)，实验范围见[研究边界](RESEARCH_BOUNDARIES_CN.md)。
